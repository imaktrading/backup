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
)

RESCUES = [
    {'from': 'Mlmtl.GX', 'to': 'Melmetal GX'},
    {'from': 'Mlmtl.gx', 'to': 'Melmetal GX'},
    {'from': 'Mlmtl', 'to': 'Melmetal'},
    {'from': 'Tony Chopper Tony Tony.Chopper', 'to': 'Tony Tony Chopper'},
]


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
    assert "TCG" in new


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
