"""Regression: 2026-08-08 — graniph 出品 CSV POC (scraper + csv_builder).

依頼書: C:/dev/iMak_data/hq/requests/2026-08-08_graniph_listing_poc_response.md

観点:
  - scraper: JSON-LD / stocks / priceData / size table parse (fixture HTML, 網なし)
  - size table: **着丈** (POC target) と **身丈** (typical) の両方に対応
  - size table: right table の header 行 <tr translate="no"> をヘッダとして取れること
  - CSV builder: SS→XXS one-down / cm→inch / material 日本語→英語 / タイトル 80字 hard cap
  - CSV builder: 親行 + variation 子行 の構造、SKU = UUID
"""
from __future__ import annotations

import io
import os
import re
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_MERCARI = _ROOT / "iMakMercari"
_API = _ROOT / "iMakeBayAPI"
for _p in (_MERCARI, _API):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


# ---- HTML fixtures (最小構成、実 HTML から抽出) ----
_HTML_FIXTURE = '''<html><head></head><body>
<script type="application/ld+json">
[{"@context": "https://schema.org/","@type": "ProductGroup",
"name": "テスト｜ハーフジップビッグシルエットTシャツ",
"description": "テスト説明",
"url": "https://www.graniph.com/item-detail/019001564303",
"brand": {"@type": "Brand","name": "テスト"},
"audience": {"@type": "PeopleAudience","suggestedGender": "unisex"},
"productGroupID": "019001564",
"material": "ポリエステル 65%  綿 35%",
"color": "ベージュ",
"image": ["https://cf.graniph.com/i1.jpg","https://cf.graniph.com/i2.jpg"],
"hasVariant": [
  {"@type":"Product","size":"SS","offers":{"availability":"https://schema.org/InStock"}},
  {"@type":"Product","size":"S","offers":{"availability":"https://schema.org/InStock"}},
  {"@type":"Product","size":"M","offers":{"availability":"https://schema.org/InStock"}},
  {"@type":"Product","size":"L","offers":{"availability":"https://schema.org/InStock"}},
  {"@type":"Product","size":"XL","offers":{"availability":"https://schema.org/InStock"}}
]}]
</script>
<script>
priceData = {"01900156430301":{"price":4900,"sale_flg":true,"sale_price":2990,"points":135},
"01900156430302":{"price":4900,"sale_flg":true,"sale_price":2990,"points":135}};
const stocks = {
  "01900156430301":{"sku_code":"01900156430301","real_quantity":20,"quantity":20,
    "sku_info":{"sku_code":"01900156430301","color_code":"303","color_label":"ベージュ","size_code":"01","size_label":"SS","item_code":"019001564303","sku_name":"x"}},
  "01900156430302":{"sku_code":"01900156430302","real_quantity":33,"quantity":33,
    "sku_info":{"sku_code":"01900156430302","color_code":"303","color_label":"ベージュ","size_code":"02","size_label":"S","item_code":"019001564303","sku_name":"x"}},
  "01900156430303":{"sku_code":"01900156430303","real_quantity":43,"quantity":43,
    "sku_info":{"sku_code":"01900156430303","color_code":"303","color_label":"ベージュ","size_code":"03","size_label":"M","item_code":"019001564303","sku_name":"x"}},
  "01900156430304":{"sku_code":"01900156430304","real_quantity":36,"quantity":36,
    "sku_info":{"sku_code":"01900156430304","color_code":"303","color_label":"ベージュ","size_code":"04","size_label":"L","item_code":"019001564303","sku_name":"x"}},
  "01900156430310":{"sku_code":"01900156430310","real_quantity":11,"quantity":11,
    "sku_info":{"sku_code":"01900156430310","color_code":"303","color_label":"ベージュ","size_code":"10","size_label":"XL","item_code":"019001564303","sku_name":"x"}}
};
</script>
<div class="p-products-detail__size-block-table-left">
  <table>
    <thead><tr><th>サイズ<br>(cm)</th></tr></thead>
    <tbody>
      <tr><th class="label"><span>着丈</span></th></tr>
      <tr><th class="label"><span>身幅</span></th></tr>
      <tr><th class="label"><span>袖丈</span></th></tr>
      <tr><th class="label"><span>肩幅</span></th></tr>
    </tbody>
  </table>
</div>
<div class="p-products-detail__size-block-table-right">
  <table>
    <thead>
      <tr translate="no">
        <th>SS</th><th>S</th><th>M</th><th>L</th><th>XL</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td translate="no">62.5</td><td translate="no">65.5</td><td translate="no">68.5</td><td translate="no">71.5</td><td translate="no">74.5</td>
      </tr>
      <tr>
        <td translate="no">53</td><td translate="no">56</td><td translate="no">59</td><td translate="no">62</td><td translate="no">65</td>
      </tr>
      <tr>
        <td translate="no">22</td><td translate="no">23.5</td><td translate="no">25</td><td translate="no">26.5</td><td translate="no">28</td>
      </tr>
      <tr>
        <td translate="no">49.5</td><td translate="no">52</td><td translate="no">54.5</td><td translate="no">57</td><td translate="no">59.5</td>
      </tr>
    </tbody>
  </table>
</div>
</body></html>
'''


# ---- 身丈 (typical) variant fixture ----
_HTML_MIJITAKE = _HTML_FIXTURE.replace("着丈", "身丈")


# ---- OOS variant fixture (SS だけ在庫切れ) ----
_HTML_SS_OOS = _HTML_FIXTURE.replace(
    '"01900156430301":{"sku_code":"01900156430301","real_quantity":20,"quantity":20',
    '"01900156430301":{"sku_code":"01900156430301","real_quantity":0,"quantity":0',
)


@pytest.fixture
def patched_scrape(monkeypatch):
    """_fetch_html を monkeypatch して HTTP を叩かせない."""
    import graniph_scraper as gs
    calls = {"count": 0}

    def _make(fx):
        def _mock(url, timeout=30):
            calls["count"] += 1
            return fx
        return _mock
    return {"gs": gs, "monkeypatch": monkeypatch, "calls": calls, "make": _make}


# ---- scraper 単体 ----
class TestScraper:
    def test_parses_basic_fields(self, patched_scrape):
        gs = patched_scrape["gs"]
        patched_scrape["monkeypatch"].setattr(gs, "_fetch_html", patched_scrape["make"](_HTML_FIXTURE))
        p = gs.scrape("https://www.graniph.com/item-detail/019001564303")
        assert p.item_code == "019001564303"
        assert p.product_group_id == "019001564"
        assert p.color_code == "303"
        assert p.color_jp == "ベージュ"
        assert p.material_jp == "ポリエステル 65%  綿 35%"
        assert p.suggested_gender == "unisex"

    def test_parses_price_regular_and_sale(self, patched_scrape):
        gs = patched_scrape["gs"]
        patched_scrape["monkeypatch"].setattr(gs, "_fetch_html", patched_scrape["make"](_HTML_FIXTURE))
        p = gs.scrape("https://www.graniph.com/item-detail/019001564303")
        assert p.price_regular_jpy == 4900
        assert p.price_sale_jpy == 2990

    def test_parses_stocks_by_size(self, patched_scrape):
        gs = patched_scrape["gs"]
        patched_scrape["monkeypatch"].setattr(gs, "_fetch_html", patched_scrape["make"](_HTML_FIXTURE))
        p = gs.scrape("https://www.graniph.com/item-detail/019001564303")
        assert p.stock == {"SS": 20, "S": 33, "M": 43, "L": 36, "XL": 11}
        assert p.sizes == ["SS", "S", "M", "L", "XL"]

    def test_oos_size_excluded_from_available(self, patched_scrape):
        gs = patched_scrape["gs"]
        patched_scrape["monkeypatch"].setattr(gs, "_fetch_html", patched_scrape["make"](_HTML_SS_OOS))
        p = gs.scrape("https://www.graniph.com/item-detail/019001564303")
        assert "SS" not in p.sizes
        assert p.sizes == ["S", "M", "L", "XL"]
        # size_all_declared には残る (SS は宣言としては存在する)
        assert "SS" in p.size_all_declared

    def test_size_table_kijitake(self, patched_scrape):
        """POC 対象商品 (019001564303) は '着丈' ラベル."""
        gs = patched_scrape["gs"]
        patched_scrape["monkeypatch"].setattr(gs, "_fetch_html", patched_scrape["make"](_HTML_FIXTURE))
        p = gs.scrape("https://www.graniph.com/item-detail/019001564303")
        assert len(p.size_table) == 4
        assert [r.label_jp for r in p.size_table] == ["着丈", "身幅", "袖丈", "肩幅"]
        assert p.size_table[0].values_cm == {"SS": 62.5, "S": 65.5, "M": 68.5, "L": 71.5, "XL": 74.5}

    def test_size_table_mijitake_also_ok(self, patched_scrape):
        """他商品は '身丈' ラベル (survey 11件中 10件がこちら)."""
        gs = patched_scrape["gs"]
        patched_scrape["monkeypatch"].setattr(gs, "_fetch_html", patched_scrape["make"](_HTML_MIJITAKE))
        p = gs.scrape("https://www.graniph.com/item-detail/019001564303")
        assert [r.label_jp for r in p.size_table] == ["身丈", "身幅", "袖丈", "肩幅"]

    def test_url_pattern_check(self):
        import graniph_scraper as gs
        with pytest.raises(ValueError, match="Not a graniph"):
            gs.scrape("https://www.graniph.com/collection/something")


# ---- CSV builder helper 単体 ----
class TestBuilderHelpers:
    def test_size_jp_to_us_one_down(self):
        import graniph_csv_builder as b
        assert b.SIZE_JP_TO_US["SS"] == "XXS"
        assert b.SIZE_JP_TO_US["S"] == "XS"
        assert b.SIZE_JP_TO_US["M"] == "S"
        assert b.SIZE_JP_TO_US["L"] == "M"
        assert b.SIZE_JP_TO_US["XL"] == "L"

    def test_cm_to_inch_precision(self):
        import graniph_csv_builder as b
        assert b.cm_to_inch(62.5) == "24.6"      # 24.606... → 24.6
        assert b.cm_to_inch(2.54) == "1.0"
        assert b.cm_to_inch(100.0) == "39.4"

    def test_material_jp_to_en(self):
        import graniph_csv_builder as b
        assert b.material_jp_to_en("ポリエステル 65%  綿 35%") == "65% Polyester, 35% Cotton"
        assert b.material_jp_to_en("綿 100%") == "100% Cotton"
        assert b.material_jp_to_en("") == ""

    def test_primary_material_picks_biggest(self):
        import graniph_csv_builder as b
        assert b.primary_material_en("ポリエステル 65%  綿 35%") == "Polyester"
        assert b.primary_material_en("綿 90% ポリウレタン 10%") == "Cotton"

    def test_color_jp_to_en_known_map(self):
        import graniph_csv_builder as b
        assert b.color_jp_to_en("ベージュ") == "Beige"
        assert b.color_jp_to_en("ブラック") == "Black"
        # unknown color → 原文 (fail-closed, romaji 化しない)
        assert b.color_jp_to_en("謎色") == "謎色"

    def test_derive_type_from_name(self):
        import graniph_csv_builder as b
        assert b.derive_type_from_name("XX｜ハーフジップビッグシルエットTシャツ") == "T-Shirt"
        assert b.derive_type_from_name("XX｜スウェット") == "Sweatshirt"
        assert b.derive_type_from_name("XX｜半袖ジップパーカー") == "Hoodie"
        assert b.derive_type_from_name("XX｜グラデーションクルーネックニット") == "Pullover Sweater"

    def test_derive_sleeve_length(self):
        import graniph_csv_builder as b
        assert b.derive_sleeve_length("XX｜長袖Tシャツ") == "Long Sleeve"
        assert b.derive_sleeve_length("XX｜半袖ジップパーカー") == "Short Sleeve"
        assert b.derive_sleeve_length("XX｜スウェット") == "Long Sleeve"

    def test_derive_fit(self):
        import graniph_csv_builder as b
        assert b.derive_fit("XX｜ハーフジップビッグシルエットTシャツ") == "Relaxed"
        assert b.derive_fit("XX｜スウェット") == "Regular"

    def test_gender_to_category(self):
        import graniph_csv_builder as b
        assert b.gender_to_category("unisex") == 15687     # Men's に寄せる (回答書承認)
        assert b.gender_to_category("male") == 15687
        assert b.gender_to_category("female") == 53159

    def test_size_label_jp_en_map_covers_kijitake_and_mijitake(self):
        import graniph_csv_builder as b
        # 着丈 (POC target) と 身丈 (typical) は両方 "Length" にマップされる
        assert b.SIZE_LABEL_JP_TO_EN["着丈"] == "Length"
        assert b.SIZE_LABEL_JP_TO_EN["身丈"] == "Length"


# ---- CSV builder E2E (scraper monkeypatch) ----
class TestBuilderE2E:
    def _mk_product(self, patched_scrape, html=_HTML_FIXTURE):
        gs = patched_scrape["gs"]
        patched_scrape["monkeypatch"].setattr(gs, "_fetch_html", patched_scrape["make"](html))
        return gs.scrape("https://www.graniph.com/item-detail/019001564303")

    def test_build_title_within_80_chars(self, patched_scrape):
        import graniph_csv_builder as b
        p = self._mk_product(patched_scrape)
        title = b.build_title(p)
        assert len(title) <= 80
        assert "Graniph" in title    # SEO 担保 (回答書指示)

    def test_size_table_html_uses_inch(self, patched_scrape):
        import graniph_csv_builder as b
        p = self._mk_product(patched_scrape)
        html = b.build_size_table_html(p.size_table, p.sizes)
        assert "(inch)" in html
        # 62.5 cm → 24.6 inch
        assert "24.6" in html
        # cm 生値が漏れていない
        assert ">62.5<" not in html

    def test_description_includes_about_graniph(self, patched_scrape):
        import graniph_csv_builder as b
        p = self._mk_product(patched_scrape)
        desc = b.build_description_html(p, p.sizes)
        assert "About Graniph" in desc
        assert "Osaka" in desc
        assert "Japan-exclusive" in desc

    def test_parent_row_columns_match_headers(self, patched_scrape):
        import graniph_csv_builder as b
        p = self._mk_product(patched_scrape)
        row = b.build_parent_row(p, p.sizes, 10.98, "60-100", "sku-parent")
        assert len(row) == len(b.CSV_HEADERS), \
            f"parent row width {len(row)} != headers {len(b.CSV_HEADERS)}"

    def test_child_rows_columns_match_headers(self, patched_scrape):
        import graniph_csv_builder as b
        p = self._mk_product(patched_scrape)
        rows = b.build_variation_rows(p, p.sizes, 10.98, "sku-parent")
        assert len(rows) == len(p.sizes)
        for r in rows:
            assert len(r) == len(b.CSV_HEADERS)
        # Size 列に "US (JP)" 併記
        idx_size = b.CSV_HEADERS.index("C:Size")
        assert rows[0][idx_size] == "XXS (JP SS)"        # SS → XXS
        assert rows[4][idx_size] == "L (JP XL)"          # XL → L
        # SKU は UUID 形式 (14桁 sku_code ではない)
        idx_sku = b.CSV_HEADERS.index("CustomLabel")
        assert re.match(r"^[0-9a-f]{8}-", rows[0][idx_sku]), \
            f"expected UUID SKU, got {rows[0][idx_sku]}"
        # 全 SKU がユニーク
        skus = [r[idx_sku] for r in rows]
        assert len(set(skus)) == len(skus)

    def test_brand_uses_free_text_graniph(self, patched_scrape):
        """回答書: eBay Brand フィルタに Graniph が無い → free text."""
        import graniph_csv_builder as b
        p = self._mk_product(patched_scrape)
        row = b.build_parent_row(p, p.sizes, 10.98, "60-100", "sku-parent")
        idx_brand = b.CSV_HEADERS.index("C:Brand")
        assert row[idx_brand] == "Graniph"

    def test_relationship_details_uses_us_jp_format(self, patched_scrape):
        import graniph_csv_builder as b
        p = self._mk_product(patched_scrape)
        row = b.build_parent_row(p, p.sizes, 10.98, "60-100", "sku-parent")
        idx_rel = b.CSV_HEADERS.index("RelationshipDetails")
        rel = row[idx_rel]
        assert rel.startswith("Size=")
        for jp, us in [("SS", "XXS"), ("S", "XS"), ("M", "S"), ("L", "M"), ("XL", "L")]:
            assert f"{us} (JP {jp})" in rel


# ---- category_to_group 追加確認 ----
def test_yaml_has_graniph_in_category_to_group():
    """回答書指示: config/global.yaml に 'graniph': C を追加."""
    yaml_path = _ROOT / "iMakeBayAPI" / "config" / "global.yaml"
    text = yaml_path.read_text(encoding="utf-8")
    # category_to_group ブロック内に "graniph": C が存在すること
    assert re.search(r'"graniph"\s*:\s*C', text), \
        "graniph → group C mapping missing from config/global.yaml"


def test_v6_group_lookup_returns_c_for_graniph():
    """pricing_engine._v6_group('graniph') が C を返すこと (yaml 経由)."""
    sys.path.insert(0, str(_API))
    from pricing_engine import _v6_group
    assert _v6_group("graniph") == "C"


def test_shipping_profile_uses_group_c_for_graniph():
    """graniph は group C 前提。price=$50 → tier P06 → DDP-C-P06 想定."""
    sys.path.insert(0, str(_API))
    from listing_common import get_shipping_policy_name
    prof = get_shipping_policy_name(50.0, "graniph")
    assert prof.startswith("DDP-C-"), f"expected DDP-C-*, got {prof}"
