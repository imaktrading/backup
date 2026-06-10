"""variation qty=0 verify の per-SKU 化 regression (2026-06-10).

旧 bug: 多 variation listing の qty=0 verify が top-level <Quantity> (= 全 variation sum)
を読み、 1 SKU 取下げても他 SKU 在庫で sum>0 → 永遠に false-NG (= 偽 ⚠️要対応 / 無駄リトライ、
実際は取下げ成功済)。 修正: specifics 一致 variation の available = Quantity - QuantitySold。
公式監視くん 358275199203 等 3 件が verify_qty=22/41/3 (= listing 合計) で false-NG だった。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ebay_actions.trading_api_uploader import _extract_variation_available  # noqa: E402


def _variation(size, color, qty, sold):
    color_nvl = (
        f"<NameValueList><Name>Color</Name><Value>{color}</Value></NameValueList>"
        if color else ""
    )
    return (
        "<Variation><SKU>sku-x</SKU>"
        f"<Quantity>{qty}</Quantity>"
        "<VariationSpecifics>"
        f"<NameValueList><Name>Sizes</Name><Value>{size}</Value></NameValueList>"
        f"{color_nvl}"
        "</VariationSpecifics>"
        f"<SellingStatus><QuantitySold>{sold}</QuantitySold></SellingStatus>"
        "</Variation>"
    )


# 多 variation listing: 対象 SKU=取下げ済(0)、 他 SKU=在庫あり (= 旧 bug の罠)
SAMPLE_XML = (
    "<Variations>"
    + _variation("US S(JP M)", "BL", 0, 0)    # 対象 = 取下げ済
    + _variation("US S(JP M)", "NV", 1, 0)    # 他 SKU 在庫あり
    + _variation("JP L", "YL", 5, 5)          # 売り切れ (Quantity=sold → available 0)
    + _variation("US M(JP L)", "OG", 8, 2)    # 在庫あり available 6
    + "</Variations>"
)


def test_taken_down_sku_returns_available_zero():
    # 旧 bug ではここで listing 合計 (0+1+5+8 - sold) を読んで false-NG だった
    assert _extract_variation_available(SAMPLE_XML, {"Sizes": "US S(JP M)", "Color": "BL"}) == 0


def test_in_stock_sku_returns_positive():
    assert _extract_variation_available(SAMPLE_XML, {"Sizes": "US M(JP L)", "Color": "OG"}) == 6


def test_sold_out_via_quantity_equals_sold():
    # Quantity=5 sold=5 → available 0 (取下げ済扱い)
    assert _extract_variation_available(SAMPLE_XML, {"Sizes": "JP L", "Color": "YL"}) == 0


def test_no_color_spec_single_dimension():
    xml = "<Variations>" + _variation("US XL(JP XXL)", "", 0, 0) + "</Variations>"
    assert _extract_variation_available(xml, {"Sizes": "US XL(JP XXL)"}) == 0


def test_specifics_not_found_returns_none():
    assert _extract_variation_available(SAMPLE_XML, {"Sizes": "US S(JP M)", "Color": "ZZ"}) is None
