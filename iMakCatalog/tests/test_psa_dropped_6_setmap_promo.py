"""2026-06-10 PSA出品で脱落した Pokemon 6件の resolve 回帰 (HQ依頼).

requests/2026-06-10_psa_dropped_6_pokemon_setmap_promo.md
真因: A) brand→set_code 索引未到達 (records 実在), B) 'S PROMO' が generic
PROMO→'P' に落ちて P-288 誤引き, C) McDonald's promo M-P-020 未収録。

真値裏取り:
  - SM8b/SM10b/SI/S-P: catalog set_name(スカイレジェンド等) + records 実在で確定
  - M-P-020: pokemon-card.com card/48258 (マクドナルド ハッピーセット2025, 2025年配布)
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "integrations"))
import psa_to_csv as P  # noqa: E402

# (cert, brand, card_no, subject, expected_pid)
CASES = [
    ("109940063", "POKEMON JAPANESE SUN & MOON SKY LEGEND", "053",
     "LILLIE-HOLO SKY LEGEND", "SM10b-053"),
    ("74118843", "POKEMON JAPANESE SUN & MOON ULTRA SHINY GX", "214",
     "FA/ARTICUNO GX ULTRA SHINY GX", "SM8b-214"),
    ("139561995", "POKEMON JAPANESE SWORD & SHIELD START DECK 100", "127",
     "PIKACHU-REV.FOIL START DECK 100", "SI-127"),
    ("131214875", "POKEMON JAPANESE S PROMO", "288",
     "ALOLAN EXEGGUTOR V POKEMON GO PR.CRD.GFT.CP.", "S-P-288"),
    ("126900241", "POKEMON JAPANESE S PROMO", "265",
     "FA/PIKACHU VMAX COROCORO COMIC FEB.'22", "S-P-265"),
    ("127272109", "POKEMON JAPANESE M-P PROMO", "020",
     "PIKACHU MCDONALD'S", "M-P-020"),
]


def test_all_six_resolve_to_expected_pid():
    for cert, brand, num, subj, expected in CASES:
        r = P.lookup_pokemon(brand, num, subj, verbose=False)
        assert r is not None, f"cert {cert} unresolved (was a CSV drop)"
        assert r["card_id"] == expected, f"cert {cert}: {r['card_id']} != {expected}"


def test_s_promo_no_longer_falls_to_generic_P():
    # 真因の核: 'S PROMO' は S-P に解決し、generic 'P' に落ちない
    assert P.extract_set_code_from_brand_pokemon("POKEMON JAPANESE S PROMO") == "S-P"


def test_new_promo_patterns_no_collision():
    # SM/SV/XY PROMO は従来通り (S PROMO 追加で誤変化しない)
    assert P.extract_set_code_from_brand_pokemon("POKEMON JAPANESE SM PROMO") == "SMP"
    assert P.extract_set_code_from_brand_pokemon("POKEMON JAPANESE SV PROMO") == "SV-P"
    assert P.extract_set_code_from_brand_pokemon("POKEMON JAPANESE XY PROMO") == "XYP"
    # 素の 'PROMO' は引き続き generic 'P'
    assert P.extract_set_code_from_brand_pokemon("POKEMON JAPANESE PROMO") == "P"
