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


# ----- eBay 禁止文字ガード (2026-07-18: DBSCG 'C★' 入稿失敗 ErrorCode 240 を受けて追加) -----
from post_title_fix import strip_ebay_banned_chars   # noqa: E402


def test_strip_star_from_title():
    """★ (DBSCG rarity marker) をタイトルから除去 = 入稿失敗の直接原因を潰す."""
    new, changed = strip_ebay_banned_chars("PSA 10 Dragon Ball Japanese Promo Cards #FS04-11 Frieza C★ 2025")
    assert changed and "★" not in new
    assert new == "PSA 10 Dragon Ball Japanese Promo Cards #FS04-11 Frieza C 2025"


def test_strip_various_banned_chars():
    for bad in ("SR★", "Card™", "½ Set", "H₂O", "x²", "♥ Love"):
        new, changed = strip_ebay_banned_chars(bad)
        assert changed, f"{bad!r} should be flagged"
        assert not any(c in new for c in "★™½₂²♥")


def test_accented_letters_preserved():
    """é (Pokémon) は eBay 許容 → 絶対に除去しない (curated set の要)."""
    new, changed = strip_ebay_banned_chars("PSA 10 Pokémon Crimson Haze #091 Card")
    assert not changed and new == "PSA 10 Pokémon Crimson Haze #091 Card"


def test_strip_banned_idempotent_and_noop():
    clean = "PSA 10 One Piece #EB03-053 Nami Super Rare"
    new, changed = strip_ebay_banned_chars(clean)
    assert not changed and new == clean


def test_fix_title_strips_banned():
    """fix_title パイプラインに組み込まれている (title 経路)."""
    new, log = fix_title("PSA 10 Dragon Ball Promo #FS04-11 Frieza C★ 2025", "Japanese", "C★", RESCUES)
    assert "★" not in new and log['banned_strip'] is True


def test_process_csv_sanitizes_item_specifics(tmp_path):
    """★★★ 本命: C:Rarity='C★' (item specific) も除去する = title だけ直しても入稿失敗は残る穴を塞ぐ.

    実際の Frieza FS04-11 failure (2026-07-18) を再現: title + C:Rarity 両方に ★。
    """
    import csv as _csv
    csv_path = str(tmp_path / "tcg_upload_frieza.csv")
    headers = ['*Title', 'C:Rarity', 'C:Language', 'C:Set']
    with open(csv_path, 'w', encoding='utf-8', newline='') as f:
        w = _csv.writer(f, quoting=_csv.QUOTE_NONNUMERIC)
        w.writerow(headers)
        w.writerow(["PSA 10 Dragon Ball Japanese Promo Cards #FS04-11 Frieza C★ 2025",
                    "C★", "Japanese", "Promo Cards"])
    from post_title_fix import process_csv
    stats = process_csv(csv_path, RESCUES, log_func=lambda m: None)
    assert stats['banned_stripped'] == 1        # title
    assert stats['spec_banned_stripped'] == 1   # C:Rarity
    # 書き戻し後に ★ がCSV全体から消えていること (入稿失敗の根絶)
    with open(csv_path, encoding='utf-8') as f:
        assert "★" not in f.read()
    # C:Rarity が 'C' になっている (値の正規化=Common化は Catalog SSOT の別レイヤ)
    with open(csv_path, encoding='utf-8', newline='') as f:
        row = list(_csv.reader(f))[1]
    assert row[1] == "C" and "★" not in row[0]


def test_description_html_whitespace_preserved():
    """Description(HTML)は ★ を消しても改行/インデントを潰さない (collapse_ws=False)."""
    html = "<ul>\n  <li><b>Rarity:</b> C★</li>\n  <li><b>Year:</b> 2025</li>\n</ul>"
    new, changed = strip_ebay_banned_chars(html, collapse_ws=False)
    assert changed and "★" not in new
    assert new == "<ul>\n  <li><b>Rarity:</b> C</li>\n  <li><b>Year:</b> 2025</li>\n</ul>"
    assert "\n" in new and "  <li>" in new   # 改行・インデント保持


def test_process_csv_sanitizes_description(tmp_path):
    """Description 内の Specs ブロック 'Rarity: C★' も除去 (240 の description 経路)."""
    import csv as _csv
    csv_path = str(tmp_path / "tcg_upload_desc.csv")
    headers = ['*Title', '*Description', 'C:Rarity', 'C:Language']
    desc = "<html><body>\n<ul>\n  <li><b>Rarity:</b> C★</li>\n</ul>\n</body></html>"
    with open(csv_path, 'w', encoding='utf-8', newline='') as f:
        w = _csv.writer(f, quoting=_csv.QUOTE_NONNUMERIC)
        w.writerow(headers)
        w.writerow(["PSA 10 Dragon Ball SCG #FS04-11 Frieza Card Long Enough Title Here", desc, "C★", "Japanese"])
    from post_title_fix import process_csv
    process_csv(csv_path, RESCUES, log_func=lambda m: None)
    with open(csv_path, encoding='utf-8') as f:
        content = f.read()
    assert "★" not in content            # description + spec 両方から消えた
    assert "\n" in content               # HTML 改行が残っている


def test_process_csv_star_triggers_backup(tmp_path):
    """★ 除去だけでも backup + 書戻しが発火する (title 無変更・spec のみ変更ケース)."""
    import csv as _csv
    csv_path = str(tmp_path / "tcg_upload_speconly.csv")
    headers = ['*Title', 'C:Rarity', 'C:Language']
    with open(csv_path, 'w', encoding='utf-8', newline='') as f:
        w = _csv.writer(f, quoting=_csv.QUOTE_NONNUMERIC)
        w.writerow(headers)
        # title は綺麗で十分長い (no-op) だが C:Rarity に ★
        w.writerow(["PSA 10 Dragon Ball SCG Awakened Pulse #FB01-071 Son Gohan Childhood Card", "L★", "Japanese"])
    from post_title_fix import process_csv
    stats = process_csv(csv_path, RESCUES, log_func=lambda m: None)
    assert stats['spec_banned_stripped'] == 1
    assert stats['unchanged'] == 0              # spec 変更もカウントされ unchanged にしない
    assert len(list(tmp_path.glob("*.bak_post_title_*"))) == 1
