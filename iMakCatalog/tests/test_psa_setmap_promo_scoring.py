"""PSA adapter 回帰テスト (2026-06-09 HQ依頼: catalog miss = mapping/scoring問題).

① PEERLESS FIGHTERS(双璧のファイター=S5a) の set_code 抽出
② Best Selection vol.4 brand で promo fallback が日本語 set_name の _p1 を最優先で拾う
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "integrations"))
import psa_to_csv as P  # noqa: E402


def test_peerless_fighters_maps_to_s5a():
    assert P.extract_set_code_from_brand_pokemon(
        "POKEMON JAPANESE SWORD & SHIELD PEERLESS FIGHTERS") == "S5a"


def test_swsh_brand_set_code_mappings():
    # 2026-06-09 HQ: SwSh PSA英語セット名→set_code 欠落の補完
    cases = [
        ("POKEMON JAPANESE SWORD & SHIELD FUSION ARTS", "S8"),
        ("POKEMON JAPANESE SWORD & SHIELD REBELLION CRASH", "S2"),
    ]
    for brand, exp in cases:
        assert P.extract_set_code_from_brand_pokemon(brand) == exp, brand


def test_best_selection_vol4_promo_picks_p1():
    # Sabo: 汎用 _P/_P_BS4('Promotion Card', 220点)でなく _p1(日本語'ベストセレクション vol.4')を選ぶ
    r = P._search_one_piece_promo_by_number(
        "049", "SABO",
        brand="ONE PIECE JAPANESE PREMIUM CARD COLLECTION -BEST SELECTION VOL.4-",
        verbose=False)
    assert r is not None and r["product_id"] == "OP10-049_p1"


def test_op10_049_p1_set_name_ebay_filled():
    import api
    r = api.lookup(category="one_piece_tcg", product_id="OP10-049_p1")
    assert r and r["set_name"] == "Premium Card Collection - Best Selection vol.4"
