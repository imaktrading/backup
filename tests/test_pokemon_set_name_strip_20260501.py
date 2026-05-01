"""Regression: 2026-05-01 Pokemon CSV 汚染事故 (4件 list 拡張対応).

事故 (csv_output/tcg_upload_20260501_174341.csv):
  Row 1 cert 143595907  Ho-Oh V       : C:Card Name = "Ho-Oh V Incandescent Arcana" (set 名混入)
                                        Title = "... Ho-Oh V Card Ho-Oh V Incandescent Arcana" (重複)
  Row 4 cert 141530622  Umbreon Vmax  : Title = "... Umbreon Vmax Fa/Umbreon Vmax Eevee Heroes" (Fa/+重複)
                                        C:Card Name = "Umbreon Vmax Eevee Heroes" (set 名混入)
  Row 5 cert 150033460  Gengar ex     : C:Card Name = "Gengar Ex Super" (rarity 単語混入)
  Row 6 cert 139761885  Gengar-Holo   : C:Card Name = "Gengar-Holo Shiny Star V" (set 名混入)
                                        Title = "... Gengar-Holo Card Gengar-Holo Shiny Star V" (重複)

修正方針 (本体 logic 不変、list 拡張のみ):
  Fix A: iMakTCG/psa_to_csv.py _pokemon_card_name の strip_patterns に
         Pokemon set 名 (INCANDESCENT ARCANA, EEVEE HEROES 等) と
         Pokemon prefix (^FA/, ^AR/, ^SAR/ 等) を追加.
         → character 段階で剥がす → refine_title が clean character を受け取る
         → _ensure_character_in_title が "no-op" (substring check pass) → 重複/Fa/復活ゼロ.
  Fix B: iMakTCG/card_name_normalizer.py _POKEMON_SUFFIXES に同 set 名追加 (defense in depth).

本テストは Fix A + B を物理ギブス化.
"""
from __future__ import annotations
import importlib.util
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TCG = _REPO_ROOT / "iMakTCG"
if str(_TCG) not in sys.path:
    sys.path.insert(0, str(_TCG))


def _load_module_by_path(path: Path, name: str):
    """sys.path 競合回避用、絶対パスから module load."""
    spec = importlib.util.spec_from_file_location(name, str(path))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


_psa_tcg = _load_module_by_path(_TCG / "psa_to_csv.py", "_test_psa_to_csv_tcg_set")


# ============================================================================
# Fix A: _pokemon_card_name の set 名 + prefix 剥がし
# ============================================================================
def test_pokemon_card_name_strips_incandescent_arcana():
    """'HO-OH V INCANDESCENT ARCANA' → 'Ho-Oh V' (Row 1 Ho-Oh)."""
    fn = _psa_tcg._pokemon_card_name
    assert fn("HO-OH V INCANDESCENT ARCANA") == "Ho-Oh V"


def test_pokemon_card_name_strips_eevee_heroes_with_prefix():
    """'FA/UMBREON VMAX EEVEE HEROES' → 'Umbreon Vmax' (Row 4 Umbreon Vmax)."""
    fn = _psa_tcg._pokemon_card_name
    assert fn("FA/UMBREON VMAX EEVEE HEROES") == "Umbreon Vmax"


def test_pokemon_card_name_strips_super_rarity():
    """'GENGAR EX SUPER' → 'Gengar Ex' (Row 5 Gengar Ex Super、SUPER 単独)."""
    fn = _psa_tcg._pokemon_card_name
    assert fn("GENGAR EX SUPER") == "Gengar Ex"


def test_pokemon_card_name_strips_shiny_star_v():
    """'GENGAR-HOLO SHINY STAR V' → 'Gengar-Holo' (Row 6 Gengar-Holo)."""
    fn = _psa_tcg._pokemon_card_name
    assert fn("GENGAR-HOLO SHINY STAR V") == "Gengar-Holo"


def test_pokemon_card_name_strips_dark_phantasma_with_prefix():
    """'FA/GENGAR DARK PHANTASMA' → 'Gengar' (cert 143375497 Gengar Dark Phantasma)."""
    fn = _psa_tcg._pokemon_card_name
    assert fn("FA/GENGAR DARK PHANTASMA") == "Gengar"


def test_pokemon_card_name_strips_vstar_universe_with_prefix():
    """'FA/RAYQUAZA VMAX VSTAR UNIVERSE' → 'Rayquaza Vmax' (Row 3 Rayquaza Vmax)."""
    fn = _psa_tcg._pokemon_card_name
    assert fn("FA/RAYQUAZA VMAX VSTAR UNIVERSE") == "Rayquaza Vmax"


def test_pokemon_card_name_strips_remix_bout():
    """'PSYDUCK REMIX BOUT' → 'Psyduck' (cert 137607102, 18:46 run 重複対応)."""
    fn = _psa_tcg._pokemon_card_name
    assert fn("PSYDUCK REMIX BOUT") == "Psyduck"


def test_pokemon_card_name_existing_behavior_preserved():
    """既存挙動: 既存パターンで動作する subject は変化しない."""
    fn = _psa_tcg._pokemon_card_name
    # 既存: SPECIAL ART RARE 系
    assert fn("EEVEE EX SPECIAL ART") == "Eevee Ex"
    assert fn("MEGA SCRAFTY EX MEGA ATTACK") == "Mega Scrafty Ex"
    # set 名なし、prefix なし → 不変
    assert fn("PIKACHU EX") == "Pikachu Ex"
    assert fn("RADIANT CHARIZARD") == "Radiant Charizard"


def test_pokemon_card_name_does_not_overstrip():
    """副作用回避: 部分一致での誤剥がし無し."""
    fn = _psa_tcg._pokemon_card_name
    # "FA/" は単独で word boundary、'FAB/' のような偽 prefix にはマッチしない (^固定)
    # ('FAB/' は実在しないが念のため)
    # 'SUPER' 単独 suffix は subject 中間にあれば残る
    assert "Super" in fn("SUPER MEGA EX")  # 'SUPER MEGA EX' → 'Super Mega Ex'


# ============================================================================
# Fix B: card_name_normalizer._POKEMON_SUFFIXES (defense in depth)
# ============================================================================
def test_card_name_normalizer_strips_incandescent_arcana():
    """defense in depth: 上流が剥がせなくても normalize_card_name でカバー."""
    from card_name_normalizer import normalize_card_name
    assert normalize_card_name("Ho-Oh V Incandescent Arcana", "Pokemon") == "Ho-Oh V"


def test_card_name_normalizer_strips_eevee_heroes():
    from card_name_normalizer import normalize_card_name
    assert normalize_card_name("Umbreon Vmax Eevee Heroes", "Pokemon") == "Umbreon Vmax"


def test_card_name_normalizer_strips_shiny_star_v():
    from card_name_normalizer import normalize_card_name
    assert normalize_card_name("Gengar-Holo Shiny Star V", "Pokemon") == "Gengar-Holo"


def test_card_name_normalizer_strips_super_suffix():
    from card_name_normalizer import normalize_card_name
    assert normalize_card_name("Gengar Ex Super", "Pokemon") == "Gengar Ex"
