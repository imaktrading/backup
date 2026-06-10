"""SwSh全弾 PSA brand→set_code 体系整備の回帰 (2026-06-10 HQ依頼: もぐら叩き終了).

PSA brand 'POKEMON JAPANESE SWORD & SHIELD <literal英名>' → catalog set_code 全hit。
真値: Bulbapedia/PSA/StockX 裏取り。SWORD/SHIELD(S1W/S1H)は era名衝突で意図的除外。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "integrations"))
import psa_to_csv as P  # noqa: E402

SWSH = {
    # 既出4件 (regression: 壊さない)
    "PEERLESS FIGHTERS": "S5a", "FUSION ARTS": "S8", "REBELLION CRASH": "S2",
    # 2026-06-10 体系整備分
    "JET-BLACK SPIRIT": "S6K", "INFINITY ZONE": "S3", "EXPLOSIVE WALKER": "S2a",
    "LEGENDARY HEARTBEAT": "S3a", "ASTONISHING VOLT TACKLE": "S4",
    "SINGLE STRIKE MASTER": "S5I", "RAPID STRIKE MASTER": "S5R",
    "SILVER LANCE": "S6H", "SKYSCRAPING PERFECT": "S7D", "BLUE SKY STREAM": "S7R",
    "POKEMON GO": "S10b",
}


def test_swsh_brand_to_set_code_all_hit():
    for name, code in SWSH.items():
        brand = f"POKEMON JAPANESE SWORD & SHIELD {name}"
        assert P.extract_set_code_from_brand_pokemon(brand) == code, f"{name}->{code}"


def test_swsh_perfection_variant_also_hits():
    # 'SKYSCRAPING PERFECTION'(別表記) も S7D
    assert P.extract_set_code_from_brand_pokemon(
        "POKEMON JAPANESE SWORD & SHIELD SKYSCRAPING PERFECTION") == "S7D"


def test_swsh_no_collision_existing_sets():
    # 既存の S系 keyword が新規追加で誤変化しない
    assert P.extract_set_code_from_brand_pokemon(
        "POKEMON JAPANESE SWORD & SHIELD EEVEE HEROES") == "S6a"
    assert P.extract_set_code_from_brand_pokemon(
        "POKEMON JAPANESE SWORD & SHIELD STAR BIRTH") == "S9"


def test_swsh_high_class_decks():
    # 2026-06-11: ハイクラスデッキ (records 実在・索引追加) cert139761896 等
    assert P.extract_set_code_from_brand_pokemon(
        "POKEMON JAPANESE SWORD & SHIELD GENGAR VMAX HIGH-CLASS DECK") == "SGG"
    assert P.extract_set_code_from_brand_pokemon(
        "POKEMON JAPANESE SWORD & SHIELD INTELEON VMAX HIGH-CLASS DECK") == "SGI"
