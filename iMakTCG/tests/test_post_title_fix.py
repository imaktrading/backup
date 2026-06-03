"""post_title_fix.py のテスト.

CLAUDE.md Step 6 の「バグ＝テスト追加運用」準拠.
2026-05-02 タイトル長補強・PSA 名前正規化の流出を受けて作成.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))

from post_title_fix import (
    apply_rescue,
    remove_redundant_pokemon,
    pad_title,
    fix_title,
    strip_japanese,
)

RESCUES = [
    {'from': 'Mlmtl.GX', 'to': 'Melmetal GX'},
    {'from': 'Mlmtl.gx', 'to': 'Melmetal GX'},
    {'from': 'Mlmtl', 'to': 'Melmetal'},
    {'from': 'Tony Chopper Tony Tony.Chopper', 'to': 'Tony Tony Chopper'},
]


# ----- strip_japanese (2026-06-03 Gundam リソース 混入再発を受けて追加) -----
def test_strip_japanese_gundam_resource():
    """TitleAgent が JP 名でパディングした 'リソース' が除去されること."""
    title = "PSA 10 Gundam TCG Promo Cards #RP-009 Resource リソース Japanese"
    new, changed = strip_japanese(title)
    assert changed is True
    assert "リソース" not in new
    assert new == "PSA 10 Gundam TCG Promo Cards #RP-009 Resource Japanese"


def test_strip_japanese_english_untouched():
    """英語のみのタイトルは無傷 (over-strip しない)."""
    title = "PSA 10 Pokemon Mega Dimension #229/193 Hawlucha Ex Card"
    new, changed = strip_japanese(title)
    assert changed is False
    assert new == title


def test_strip_japanese_all_kinds():
    """ひらがな/カタカナ/漢字すべて除去 + 連続スペース整理."""
    new, changed = strip_japanese("PSA 10 Test あ カ 漢 End")
    assert changed is True
    assert new == "PSA 10 Test End"  # 日本語消えて連続スペースも整理


def test_fix_title_strips_japanese_final_guard():
    """fix_title 全パイプラインで最終的に日本語が残らないこと."""
    new, log = fix_title(
        "PSA 10 Gundam TCG Promo Cards #RP-009 Resource リソース",
        language='', rarity='', rescues=[],
    )
    assert "リソース" not in new
    assert log['jp_strip'] is True
    import re
    assert not re.search(r'[぀-ヿ一-鿿]', new)


# ----- apply_rescue -----
def test_rescue_mlmtl_gx():
    title = "PSA 10 Pokemon Sun & Moon Tag Team GX All Stars #224 Lucario & Mlmtl.GX"
    new, applied = apply_rescue(title, RESCUES)
    assert "Melmetal GX" in new
    assert "Mlmtl" not in new
    assert applied  # 何らかの rescue が適用された


def test_rescue_tony_chopper_dup():
    title = "PSA 10 One Piece TCG Promo Cards #EB01-006 Tony Chopper Tony Tony.Chopper"
    new, _ = apply_rescue(title, RESCUES)
    assert "Tony Tony Chopper" in new
    assert "Tony Chopper Tony" not in new


def test_rescue_idempotent():
    """既に正規形の title に rescue を適用しても変化しないこと."""
    title = "PSA 10 One Piece TCG Promo Cards #EB01-006 Tony Tony Chopper Japanese Card"
    new, applied = apply_rescue(title, RESCUES)
    assert new == title
    assert applied == []


# ----- remove_redundant_pokemon -----
def test_dedup_pokemon_accent():
    title = "PSA 10 Pokemon GO #011 Radiant Charizard Pokémon Card"
    new, changed = remove_redundant_pokemon(title)
    assert "Pokémon" not in new
    assert "Pokemon GO" in new  # ASCII の Pokemon は残す
    assert changed


def test_dedup_no_change_when_no_accent():
    title = "PSA 10 Pokemon Eevee Heroes #048 Umbreon VMAX Card"
    new, changed = remove_redundant_pokemon(title)
    assert new == title
    assert not changed


# ----- pad_title -----
def test_pad_short_japanese_pokemon():
    title = "PSA 10 Pokemon Incandescent Arcana #055 Ho-Oh V Card"  # 52字
    new, applied = pad_title(title, language="Japanese", rarity="RR")
    assert len(new) >= 60
    assert "Japanese" in new
    # 2026-05-31: 'TCG' filler 廃止 (PDF Rank 圏外 + game 表記重複) → TCG は追加しない
    assert "TCG" not in new


def test_pad_with_secret_rare():
    title = "PSA 10 Pokemon Eevee Heroes #048 Umbreon VMAX Card"  # 50字
    new, applied = pad_title(title, language="Japanese", rarity="Secret Rare")
    assert "Secret Rare" in new
    assert "Japanese" in new
    assert "Secret Rare" in applied


def test_pad_with_shiny_holo_rare():
    title = "PSA 10 Pokemon Shiny Star V #071 Gengar-Holo Card"  # 49字
    new, applied = pad_title(title, language="Japanese", rarity="Shiny Holo Rare")
    assert "Shiny Holo Rare" in new


def test_pad_skips_common():
    """Common/Uncommon は無価値なので追加しない."""
    title = "PSA 10 Pokemon Sun & Moon Remix Bout #017 Psyduck Card"  # 54字
    new, applied = pad_title(title, language="Japanese", rarity="Common")
    assert "Common" not in new
    # でも Japanese / TCG は付くはず
    assert "Japanese" in new or "TCG" in new


def test_pad_no_change_for_long_title():
    title = "PSA 10 Pokemon VSTAR Universe #108 Rayquaza VMAX Secret Rare Japanese Card"  # 75字
    new, applied = pad_title(title, language="Japanese", rarity="Secret Rare")
    assert new == title
    assert applied == []


def test_pad_respects_max_len():
    """80字を超える追加はしない."""
    # 既に長いタイトルに無理矢理 pad しても 80 字を超えない
    title = "PSA 10 Pokemon Some Very Long Set Name Here #999 Subject Name X"  # 約63字
    new, applied = pad_title(title, language="Japanese", rarity="Secret Rare")
    assert len(new) <= 80


# ----- fix_title (統合) -----
def test_fix_title_full_pipeline_mlmtl():
    title = "PSA 10 Pokemon Sun & Moon Tag Team GX All Stars #224 Lucario & Mlmtl.GX"
    new, log = fix_title(title, language="Japanese", rarity="Secret Rare", rescues=RESCUES)
    assert "Melmetal GX" in new
    assert log['rescue']  # rescue が適用された


def test_fix_title_full_pipeline_pokemon_go():
    title = "PSA 10 Pokemon GO #011 Radiant Charizard Pokémon Card"
    new, log = fix_title(title, language="Japanese", rarity="Radiant Rare", rescues=RESCUES)
    assert "Pokémon" not in new
    assert log['pokemon_dedup']
    # Radiant Rare → Holo に変換されて追加される
    assert "Holo" in new


def test_fix_title_no_change_for_already_good():
    title = "PSA 10 One Piece TCG Heroines Edition #EB03-061 Uta Card"  # 56字
    new, log = fix_title(title, language="Japanese", rarity="Common", rescues=RESCUES)
    # rescue 不要、pokemon_dedup 不要、pad で Japanese 等追加される可能性
    assert log['rescue'] == []
    assert not log['pokemon_dedup']


# ----- process_csv backup behavior (2026-05-09: 無修正時の backup 抑止) -----
def _write_min_csv(path, title):
    """最小 CSV を書き出すヘルパー (header + 1 row)."""
    import csv as _csv
    headers = ['*Title', 'C:Rarity', 'C:Language']
    with open(path, 'w', encoding='utf-8', newline='') as f:
        w = _csv.writer(f, quoting=_csv.QUOTE_NONNUMERIC)
        w.writerow(headers)
        w.writerow([title, 'Common', 'Japanese'])


def test_process_csv_no_backup_when_unchanged(tmp_path):
    """書換え発生しなかったら backup ファイルを作らない (リソース節約)."""
    from post_title_fix import process_csv
    csv_path = str(tmp_path / "tcg_upload_unchanged.csv")
    # 既に十分長い綺麗なタイトル → fix_title は no-op
    _write_min_csv(csv_path, "PSA 10 Pokemon SV9a #080 Cynthia's Garchomp ex Heat Wave Card")
    stats = process_csv(csv_path, RESCUES, log_func=lambda m: None)
    # 書換えなしを確認
    assert stats['rescued'] == 0
    assert stats['padded'] == 0
    assert stats['pokemon_dedup'] == 0
    assert stats['unchanged'] == 1
    # backup ファイルが作られていないこと
    bak_files = list(tmp_path.glob("*.bak_post_title_*"))
    assert bak_files == [], f"unexpected backup created: {bak_files}"


def test_process_csv_backup_when_modified(tmp_path):
    """書換え発生時は backup を作成 (安全策維持)."""
    from post_title_fix import process_csv
    csv_path = str(tmp_path / "tcg_upload_modified.csv")
    # rescue 対象 (Mlmtl.GX → Melmetal GX)
    _write_min_csv(
        csv_path,
        "PSA 10 Pokemon Sun & Moon Tag Team GX All Stars #224 Lucario & Mlmtl.GX",
    )
    stats = process_csv(csv_path, RESCUES, log_func=lambda m: None)
    assert stats['rescued'] == 1
    # backup ファイルが作成されたこと
    bak_files = list(tmp_path.glob("*.bak_post_title_*"))
    assert len(bak_files) == 1, f"expected 1 backup, got: {bak_files}"
