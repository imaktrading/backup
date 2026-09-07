"""3XL 以上の Men は Size Type を Big & Tall にする (2026-09-08).

実害: eBay が `"Regular" is not a valid Size Type for the Size "3XL"` で Revise を弾き、
リバイスくんの日次 値段更新が **その1件だけ毎日失敗**していた (9/01・9/02・9/08 同一 itemID)。
判定は ②出品くん側 — Size Type を "Regular" 固定で出していた。
実測: itemID 356740464473 を Big & Tall に直したら通った。2XL は Regular のままで通っている。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT / "iMakeBayAPI", ROOT / "iMakMercari"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import listing_common as L  # noqa: E402


def test_men_3xl_and_above_is_big_and_tall():
    for s in ("3XL", "4XL", "5XL", "6XL", "XXXL"):
        assert L.size_type_for(s, "Men") == "Big & Tall", s


def test_smaller_sizes_stay_regular():
    """2XL は Regular で通っている実績があるので広げない (推測で変えない)."""
    for s in ("XS", "S", "M", "L", "XL", "2XL"):
        assert L.size_type_for(s, "Men") == "Regular", s


def test_non_men_is_regular():
    assert L.size_type_for("3XL", "Women") == "Regular"
    assert L.size_type_for("3XL", "Unisex Adults") == "Regular"


def test_blank_is_regular():
    assert L.size_type_for("", "Men") == "Regular"
    assert L.size_type_for(None, None) == "Regular"


def test_generators_do_not_hardcode_regular_for_sized_rows():
    """単品を出す2本が共通実装を通っていること (固定値に戻ったら落とす)."""
    import tshirt_listing, montbell_listing
    assert tshirt_listing._size_type("3XL", "Men") == "Big & Tall"
    assert montbell_listing._size_type("3XL", "Men") == "Big & Tall"
