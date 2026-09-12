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


def test_department_does_not_change_it():
    """★2026-09-12 修正: Size Type は **eBay のカテゴリ側の決まり**で Department は関係ない。

    eBay Taxonomy API を実取得して確認 (cat 15687 / 57988 の Size の valueConstraints):
    3XL は `applicableForLocalizedAspectValues = ["Big & Tall"]`。Department 別の分岐は無い。
    9/08 の実装は Department=="Men" だけ直していたため、Department="Unisex Adults" の
    3XL (UT に多い) が "Regular" のまま出ていた。
    """
    for dept in ("Men", "Women", "Unisex Adults", "Teens", "", None):
        assert L.size_type_for("3XL", dept) == "Big & Tall", dept
        assert L.size_type_for("L", dept) == "Regular", dept


def test_numeric_and_tall_sizes_are_big_and_tall():
    """アウター (cat 57988) の数字サイズと Tall 表記も Big & Tall 限定 (eBay の実値)."""
    for s in ("52", "62", "68", "XLT", "3XLT", "Big 3X"):
        assert L.size_type_for(s, "Men") == "Big & Tall", s
    for s in ("50", "48"):
        assert L.size_type_for(s, "Men") == "Regular", s


def test_blank_is_regular():
    assert L.size_type_for("", "Men") == "Regular"
    assert L.size_type_for(None, None) == "Regular"


def test_generators_do_not_hardcode_regular_for_sized_rows():
    """単品を出す2本が共通実装を通っていること (固定値に戻ったら落とす)."""
    import tshirt_listing, montbell_listing
    assert tshirt_listing._size_type("3XL", "Men") == "Big & Tall"
    assert montbell_listing._size_type("3XL", "Men") == "Big & Tall"
    # ★2026-09-12: UT は Department="Unisex Adults" で出る行が多い
    assert tshirt_listing._size_type("3XL", "Unisex Adults") == "Big & Tall"
