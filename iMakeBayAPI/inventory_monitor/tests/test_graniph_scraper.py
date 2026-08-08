"""graniph_scraper の parse regression (2026-08-08 [IMPLEMENT-GO]).

★1丁目1番地 判定 (窓口 2026-08-08 回答書):
  ① カタログのデータは正しい (公式サイト 実測値 = 想定通り)
  ② 出品くん(監視くん)の引き方は canonical KEY (14桁 sku_code) のみ = 正
  → 「①も②も正しい」の状態 (= 新規実装なので発生源は今ここで作る)。
    LimitedAvailability を✕に倒す既存誤りは無い (これから新設)。

このテストは以下を回帰ガードする:
  - `const stocks` の real_quantity から in_stock/quantity を導出できる
  - `LimitedAvailability` = few (data-text="残り3点") を **在庫あり** で扱う
    (窓口実測 012000906300: L=残り3点 → in_stock=True, quantity=3)
  - `const priceData` の sale_flg → sale_price を supplier_price (実際に払う額) に反映
    、list_price_jpy には base (price) を保持
  - sku_code は 14桁の canonical KEY を **合成せず** そのまま使う
    (窓口 訂正2: `f"{product_id}-{size}"` 合成禁止)
  - 全サイズ売切でも "在庫あり" の JS テンプレ文字列に釣られない
    (窓口指摘: HTML 全体 grep 禁止)
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from graniph_scraper import (  # noqa: E402
    parse_graniph_html,
    parse_graniph_url,
    _stock_label_from_class,
    _is_sales_active,
)


# ---------------------------------------------------------------------------
# 実データ 012000906300 (2026-08-08 実測) を最小構成に切り詰めた fixture
# SS=10 / S=10 / M=0 / L=3(残り3点) / XL=0、sale_flg=True (base 8900 → sale 7990)
# ---------------------------------------------------------------------------
FIXTURE_906300 = r"""<!doctype html>
<html>
<head>
<script type="application/ld+json">
[
    {
        "@context": "https://schema.org/",
        "@type": "ProductGroup",
        "name": "ローリングパンダズケイトフルキモウパーカー",
        "url": "https://www.graniph.com/item-detail/012000906300",
        "productGroupID": "012000906",
        "color": "ブラウン",
        "hasVariant": [
            {"@type": "Product", "name": "SS", "size": "SS",
             "offers": {"@type": "Offer", "priceCurrency": "JPY", "price": 7990,
                        "availability": "https://schema.org/InStock"}},
            {"@type": "Product", "name": "L", "size": "L",
             "offers": {"@type": "Offer", "priceCurrency": "JPY", "price": 7990,
                        "availability": "https://schema.org/LimitedAvailability"}},
            {"@type": "Product", "name": "M", "size": "M",
             "offers": {"@type": "Offer", "priceCurrency": "JPY", "price": 7990,
                        "availability": "https://schema.org/OutOfStock"}}
        ]
    }
]
</script>
</head>
<body>
<div class="p-products-detail-option-size">
    <label class="in-stock " for="01">
        <span translate="no">SS</span>
        <span class="p-products-detail-option-size__list-status-text">在庫あり</span>
    </label>
    <label class="in-stock " for="02">
        <span translate="no">S</span>
        <span class="p-products-detail-option-size__list-status-text">在庫あり</span>
    </label>
    <label class="soldout " for="03">
        <span translate="no">M</span>
        <span class="p-products-detail-option-size__list-status-text">在庫なし</span>
    </label>
    <label class="few " for="04" data-text="残り3点">
        <span translate="no">L</span>
        <span class="p-products-detail-option-size__list-status-text">残り3点</span>
    </label>
    <label class="soldout " for="10">
        <span translate="no">XL</span>
        <span class="p-products-detail-option-size__list-status-text">在庫なし</span>
    </label>
</div>
<script>
const stocks = {"01200090630001":{"sku_code":"01200090630001","store_code":"998","inventory_type":"EC","arrived":true,"inventory_status":"STOCKED","quantity":10,"real_quantity":10,"boundary_quantity":0,"update_timestamp":1786137905806,"sku_info":{"lang":"ja_JP","sku_code":"01200090630001","status":"PUBLISHED","start_timestamp":1761490800000,"end_timestamp":4102412399000,"sales_start_timestamp":1761490800000,"sales_end_timestamp":4102412399000,"item_code":"012000906300","size_code":"01","size_label":"SS","color_code":"300","color_label":"ブラウン"}},"01200090630002":{"sku_code":"01200090630002","inventory_status":"STOCKED","quantity":10,"real_quantity":10,"sku_info":{"status":"PUBLISHED","sales_start_timestamp":1761490800000,"sales_end_timestamp":4102412399000,"size_code":"02","size_label":"S","color_code":"300","color_label":"ブラウン"}},"01200090630003":{"sku_code":"01200090630003","inventory_status":"STOCKED","quantity":0,"real_quantity":0,"sku_info":{"status":"PUBLISHED","sales_start_timestamp":1761490800000,"sales_end_timestamp":4102412399000,"size_code":"03","size_label":"M","color_code":"300","color_label":"ブラウン"}},"01200090630004":{"sku_code":"01200090630004","inventory_status":"STOCKED","quantity":3,"real_quantity":3,"sku_info":{"status":"PUBLISHED","sales_start_timestamp":1761490800000,"sales_end_timestamp":4102412399000,"size_code":"04","size_label":"L","color_code":"300","color_label":"ブラウン"}},"01200090630010":{"sku_code":"01200090630010","inventory_status":"STOCKED","quantity":0,"real_quantity":0,"sku_info":{"status":"PUBLISHED","sales_start_timestamp":1761490800000,"sales_end_timestamp":4102412399000,"size_code":"10","size_label":"XL","color_code":"300","color_label":"ブラウン"}}};
const priceData = {"01200090630001":{"price":8900,"sale_flg":true,"sale_price":7990,"points":360},"01200090630002":{"price":8900,"sale_flg":true,"sale_price":7990,"points":360},"01200090630003":{"price":8900,"sale_flg":true,"sale_price":7990,"points":360},"01200090630004":{"price":8900,"sale_flg":true,"sale_price":7990,"points":360},"01200090630010":{"price":8900,"sale_flg":true,"sale_price":7990,"points":360}};
</script>
<!-- 全サイズ売切でも '在庫あり' の JS テンプレが 1 回ヒットする再現 (窓口指摘) -->
<script>
    const stock_status = hasStock ? '在庫あり' : '在庫なし';
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# 全サイズ売切 fixture (JS テンプレの '在庫あり' 文字列に釣られないかの test)
# ---------------------------------------------------------------------------
FIXTURE_ALL_SOLDOUT = r"""<!doctype html>
<html><body>
<script type="application/ld+json">
[{"@type": "ProductGroup", "name": "SOLDOUT-TEST", "productGroupID": "999999999",
  "color": "テスト色"}]
</script>
<label class="soldout " for="03">
    <span translate="no">M</span>
    <span class="p-products-detail-option-size__list-status-text">在庫なし</span>
</label>
<script>
const stocks = {"99999999999903":{"sku_code":"99999999999903","inventory_status":"OUT_OF_STOCK","quantity":0,"real_quantity":0,"sku_info":{"status":"PUBLISHED","sales_start_timestamp":1761490800000,"sales_end_timestamp":4102412399000,"size_code":"03","size_label":"M","color_code":"999","color_label":"テスト色"}}};
const priceData = {"99999999999903":{"price":3000,"sale_flg":false,"sale_price":""}};
</script>
<!-- ここで JS テンプレの '在庫あり' 文字列 -->
<script>
    const stock_status = hasStock ? '在庫あり' : '在庫なし';
</script>
</body></html>
"""


URL_906300 = "https://www.graniph.com/item-detail/012000906300"
URL_ALL_SOLDOUT = "https://www.graniph.com/item-detail/999999999999"


# ---------------------------------------------------------------------------
# URL パーサ
# ---------------------------------------------------------------------------
def test_parse_graniph_url_extracts_12digit_product_id():
    assert parse_graniph_url(URL_906300)["product_id"] == "012000906300"


def test_parse_graniph_url_ignores_query_string():
    r = parse_graniph_url("https://www.graniph.com/item-detail/012000906300?utm_source=x")
    assert r["product_id"] == "012000906300"


def test_parse_graniph_url_supports_trailing_slash():
    r = parse_graniph_url("https://www.graniph.com/item-detail/012000906300/")
    assert r["product_id"] == "012000906300"


def test_parse_graniph_url_rejects_invalid():
    import pytest
    with pytest.raises(ValueError):
        parse_graniph_url("https://www.graniph.com/some-other-path")


# ---------------------------------------------------------------------------
# メイン parse: 906300 (SS/S 在庫 / M 売切 / L 残り3点 / XL 売切)
# ---------------------------------------------------------------------------
def test_parse_906300_yields_5_skus():
    r = parse_graniph_html(FIXTURE_906300, URL_906300)
    assert r["product_id"] == "012000906300"
    assert r["product_group_id"] == "012000906"
    assert r["color"] == "ブラウン"
    assert r["name"] == "ローリングパンダズケイトフルキモウパーカー"
    assert len(r["skus"]) == 5


def test_parse_906300_sku_codes_are_14digit_canonical():
    """訂正2 (2026-08-08 窓口): sku_code は 14桁の正規値。合成禁止。"""
    r = parse_graniph_html(FIXTURE_906300, URL_906300)
    codes = [s["sku_code"] for s in r["skus"]]
    assert codes == [
        "01200090630001", "01200090630002", "01200090630003",
        "01200090630004", "01200090630010",
    ]
    # l2Id / communication_code は uniqlo 互換のためのエイリアス、値は sku_code と同じ
    for s in r["skus"]:
        assert s["l2Id"] == s["sku_code"]
        assert s["communication_code"] == s["sku_code"]


def test_parse_906300_quantities_use_real_quantity():
    r = parse_graniph_html(FIXTURE_906300, URL_906300)
    by_size = {s["size"]: s["quantity"] for s in r["skus"]}
    # 窓口実測 (2026-08-08):
    assert by_size == {"SS": 10, "S": 10, "M": 0, "L": 3, "XL": 0}


def test_parse_906300_L_size_is_in_stock_despite_LimitedAvailability():
    """★§完成条件 4: L (LimitedAvailability, 残り3点) を✕に倒していない."""
    r = parse_graniph_html(FIXTURE_906300, URL_906300)
    L = next(s for s in r["skus"] if s["size"] == "L")
    assert L["in_stock"] is True
    assert L["quantity"] == 3
    assert "3" in L["stock_label"] or "残り" in L["stock_label"]  # "残り3点"


def test_parse_906300_M_XL_are_out_of_stock():
    r = parse_graniph_html(FIXTURE_906300, URL_906300)
    by_size = {s["size"]: s["in_stock"] for s in r["skus"]}
    assert by_size["M"] is False
    assert by_size["XL"] is False
    assert by_size["SS"] is True
    assert by_size["S"] is True


def test_parse_906300_supplier_price_is_sale_price_when_sale_flg_true():
    """§5 J = 実際に払う額: sale_flg=True → sale_price (7990)、base は list_price に温存."""
    r = parse_graniph_html(FIXTURE_906300, URL_906300)
    s = r["skus"][0]  # SS
    assert s["price_jpy"] == 8900              # 定価 (base)
    assert s["promo_price_jpy"] == 7990         # 実際に払う額 (sale)
    assert s["list_price_jpy"] == 8900          # U 列用 (= base)


def test_parse_906300_sales_active_when_within_window():
    r = parse_graniph_html(FIXTURE_906300, URL_906300, now_ms=1800000000000)
    # 2027-01 相当。sales_start 2025-10-27 ≤ now < sales_end 2100-01
    assert all(s["sales_active"] for s in r["skus"])


def test_parse_906300_sales_inactive_before_start():
    r = parse_graniph_html(FIXTURE_906300, URL_906300, now_ms=1000000000000)
    # 2001 相当。sales_start より前 → False
    assert all(s["sales_active"] is False for s in r["skus"])


# ---------------------------------------------------------------------------
# 全サイズ売切: 文字列 grep NG の回帰ガード
# ---------------------------------------------------------------------------
def test_parse_all_soldout_page_does_not_leak_in_stock_from_js_template():
    """★窓口指摘 (§4): ページ末尾 JS テンプレの '在庫あり' に釣られない."""
    r = parse_graniph_html(FIXTURE_ALL_SOLDOUT, URL_ALL_SOLDOUT)
    assert len(r["skus"]) == 1
    s = r["skus"][0]
    assert s["in_stock"] is False
    assert s["quantity"] == 0
    assert s["stock_label"] == "在庫なし"


def test_parse_all_soldout_sale_flg_false_uses_base_price():
    r = parse_graniph_html(FIXTURE_ALL_SOLDOUT, URL_ALL_SOLDOUT)
    s = r["skus"][0]
    assert s["price_jpy"] == 3000
    assert s["promo_price_jpy"] == 3000     # sale_flg=False → base に落ちる
    assert s["list_price_jpy"] == 3000


# ---------------------------------------------------------------------------
# _stock_label_from_class ヘルパ
# ---------------------------------------------------------------------------
def test_stock_label_in_stock_returns_ja():
    assert _stock_label_from_class("in-stock ", "", 10) == "在庫あり"


def test_stock_label_few_uses_data_text():
    assert _stock_label_from_class("few ", "残り3点", 3) == "残り3点"


def test_stock_label_few_falls_back_to_quantity_when_data_text_empty():
    assert _stock_label_from_class("few", "", 2) == "残り2点"


def test_stock_label_soldout():
    assert _stock_label_from_class("soldout ", "", 0) == "在庫なし"


# ---------------------------------------------------------------------------
# _is_sales_active
# ---------------------------------------------------------------------------
def test_sales_active_true_when_published_and_within_window():
    assert _is_sales_active(
        {"status": "PUBLISHED",
         "sales_start_timestamp": 1000,
         "sales_end_timestamp": 3000},
        now_ms=2000,
    ) is True


def test_sales_active_false_when_status_not_published():
    assert _is_sales_active(
        {"status": "DRAFT",
         "sales_start_timestamp": 1000,
         "sales_end_timestamp": 3000},
        now_ms=2000,
    ) is False


def test_sales_active_false_before_start():
    assert _is_sales_active(
        {"status": "PUBLISHED",
         "sales_start_timestamp": 3000,
         "sales_end_timestamp": 5000},
        now_ms=2000,
    ) is False


def test_sales_active_false_after_end():
    assert _is_sales_active(
        {"status": "PUBLISHED",
         "sales_start_timestamp": 1000,
         "sales_end_timestamp": 2000},
        now_ms=3000,
    ) is False


def test_sales_active_false_when_sku_info_missing():
    assert _is_sales_active({}, now_ms=2000) is False
