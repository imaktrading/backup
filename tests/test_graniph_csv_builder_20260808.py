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

# 2026-08-08: 他テスト (例 test_montbell_whitelist) が import 完了後に
# iMakMercari を sys.path から remove するため、後続テストで
# `import graniph_csv_builder` が失敗する。ここで先読みして sys.modules に
# 焼き付ければ、以後の import はキャッシュ経由で解決される。
import graniph_csv_builder  # noqa: E402,F401
import graniph_scraper      # noqa: E402,F401


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
    def test_size_jp_to_us_one_down_fallback_table(self):
        """SIZE_JP_TO_US は fallback (実寸が取れない時のみ)。primary は pick_us_size 経由."""
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
        # Size 列に "US (JP)" 併記 (実寸ベース、Gildan 5000 最近傍)
        # SS (chest 20.9, length 24.6) → M / XL (chest 25.6, length 29.3) → 2XL
        idx_size = b.CSV_HEADERS.index("C:Size")
        assert rows[0][idx_size] == "M (JP SS)"
        assert rows[4][idx_size] == "2XL (JP XL)"
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
        """RelationshipDetails は 実寸ベース (Gildan 5000 最近傍) で US ラベルを決める."""
        import graniph_csv_builder as b
        p = self._mk_product(patched_scrape)
        row = b.build_parent_row(p, p.sizes, 10.98, "60-100", "sku-parent")
        idx_rel = b.CSV_HEADERS.index("RelationshipDetails")
        rel = row[idx_rel]
        assert rel.startswith("Size=")
        # fixture: SS(24.6,20.9)→M / S(25.8,22.0)→L / M(27.0,23.2)→L /
        #          L(28.1,24.4)→XL / XL(29.3,25.6)→2XL
        for jp, us in [("SS", "M"), ("S", "L"), ("M", "L"), ("L", "XL"), ("XL", "2XL")]:
            assert f"{us} (JP {jp})" in rel, f"missing {us} (JP {jp}) in {rel!r}"


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


# ============================================================================
# 2026-08-08 追加: 仕入送料上乗せ (依頼書 procurement_shipping_and_size_map_response)
# ============================================================================
class TestProcurementShipping:
    """graniph 公式 ¥440 / ¥5,000+ 無料 の境界を固定する回帰テスト.
    依頼書 §3.2: 境界値 ¥4,999 / ¥5,000 / ¥5,001 の3点を必ずカバー."""

    def test_below_threshold_adds_440(self):
        import graniph_csv_builder as b
        assert b.procurement_shipping(4999) == 440

    def test_exactly_at_threshold_is_free(self):
        """¥5,000 以上で無料 (公式文言: '5,000円（税込）以上の場合')."""
        import graniph_csv_builder as b
        assert b.procurement_shipping(5000) == 0

    def test_above_threshold_is_free(self):
        import graniph_csv_builder as b
        assert b.procurement_shipping(5001) == 0

    def test_low_price_adds_440(self):
        import graniph_csv_builder as b
        assert b.procurement_shipping(2990) == 440

    def test_zero_price_still_adds_440(self):
        """商品代 ¥0 は無料閾値未満 → 送料込みで扱う (境界正規化)."""
        import graniph_csv_builder as b
        assert b.procurement_shipping(0) == 440

    def test_high_price_free(self):
        import graniph_csv_builder as b
        assert b.procurement_shipping(20000) == 0

    def test_constants_are_defined_once(self):
        """定数は1箇所定義 (回答書: 「1箇所に定義してそこだけ見れば分かる形」)."""
        import graniph_csv_builder as b
        assert b.PROCUREMENT_SHIPPING_JPY == 440
        assert b.FREE_SHIPPING_THRESHOLD_JPY == 5000

    def test_compute_listing_price_adds_shipping_to_cost(self, monkeypatch):
        """POC 対象 ¥2,990 → pricing_engine に ¥3,430 が渡ることを固定."""
        import graniph_csv_builder as b
        import pricing_engine
        captured = {}

        def _spy(cost_jpy, median_usd, category, *a, **kw):
            captured["cost_jpy"] = cost_jpy
            captured["category"] = category
            return {"price": 72.98, "status": "GO"}

        monkeypatch.setattr(pricing_engine, "compute_listing_price", _spy)
        b.compute_listing_price_usd(2990)
        assert captured["cost_jpy"] == 3430, (
            f"expected 2990+440=3430, got {captured['cost_jpy']}"
        )
        assert captured["category"] == "Tシャツ(UT)"

    def test_compute_listing_price_free_when_price_at_5000(self, monkeypatch):
        """¥5,000 の商品は送料無料 → cost = 5000 (加算ゼロ)."""
        import graniph_csv_builder as b
        import pricing_engine
        captured = {}

        def _spy(cost_jpy, median_usd, category, *a, **kw):
            captured["cost_jpy"] = cost_jpy
            return {"price": 100.0, "status": "GO"}

        monkeypatch.setattr(pricing_engine, "compute_listing_price", _spy)
        b.compute_listing_price_usd(5000)
        assert captured["cost_jpy"] == 5000


# ============================================================================
# 2026-08-08 追加: 実寸→US サイズ mapper (依頼書 §2)
# ============================================================================
class TestUsSizeFromMeasurements:
    """Gildan 5000 チャート最近傍。POC 実測 (graniph 019001564303 SS) を固定."""

    def test_gildan_chart_present_with_expected_labels(self):
        import graniph_csv_builder as b
        labels = [lbl for lbl, _, _ in b.US_UNISEX_TSHIRT_CHART]
        assert labels == ["XS", "S", "M", "L", "XL", "2XL", "3XL"]

    def test_ss_bigt_maps_to_m(self):
        """graniph 019001564303 SS: chest 20.9 / length 24.6 → US M (Gildan 20/29)."""
        import graniph_csv_builder as b
        assert b.us_size_from_measurements(20.9, 24.6) == "M"

    def test_standard_medium_maps_to_m(self):
        """chart 上 M と完全一致 (20/29) → M."""
        import graniph_csv_builder as b
        assert b.us_size_from_measurements(20.0, 29.0) == "M"

    def test_xxs_measurement_maps_to_xs(self):
        """XS チャートよりさらに小さい → XS (最小サイズ)."""
        import graniph_csv_builder as b
        assert b.us_size_from_measurements(14.0, 24.0) == "XS"

    def test_huge_measurement_maps_to_3xl(self):
        import graniph_csv_builder as b
        assert b.us_size_from_measurements(30.0, 34.0) == "3XL"


class TestPickUsSize:
    """primary=実測 / fallback=固定テーブル SIZE_JP_TO_US."""

    def _fixture_table(self):
        """POC target (019001564303) と同構造の size_table."""
        from graniph_scraper import SizeRow
        return [
            SizeRow(label_jp="着丈", values_cm={"SS": 62.5, "S": 65.5, "M": 68.5, "L": 71.5, "XL": 74.5}),
            SizeRow(label_jp="身幅", values_cm={"SS": 53.0, "S": 56.0, "M": 59.0, "L": 62.0, "XL": 65.0}),
            SizeRow(label_jp="袖丈", values_cm={"SS": 22.0}),
            SizeRow(label_jp="肩幅", values_cm={"SS": 49.5}),
        ]

    def test_uses_measurements_when_present(self):
        import graniph_csv_builder as b
        st = self._fixture_table()
        # SS: chest 53cm→20.9in, length 62.5cm→24.6in → M
        assert b.pick_us_size("SS", st) == "M"

    def test_falls_back_when_size_table_empty(self):
        import graniph_csv_builder as b
        # 実寸ゼロ → SIZE_JP_TO_US (one-down)
        assert b.pick_us_size("SS", []) == "XXS"
        assert b.pick_us_size("L", None) == "M"

    def test_falls_back_when_size_missing_from_table(self):
        """size_table はあるが該当 JP size のセルが無い → fallback."""
        import graniph_csv_builder as b
        st = self._fixture_table()
        # XXL は fixture 外 → fallback → XL
        assert b.pick_us_size("XXL", st) == "XL"

    def test_falls_back_when_only_length_present(self):
        """chest が取れない (length のみ) → fallback (実寸不十分)."""
        import graniph_csv_builder as b
        from graniph_scraper import SizeRow
        st = [SizeRow(label_jp="着丈", values_cm={"SS": 62.5})]
        assert b.pick_us_size("SS", st) == "XXS"

    def test_unknown_jp_size_returns_original(self):
        """fallback table にも無い未知サイズ → 原文."""
        import graniph_csv_builder as b
        assert b.pick_us_size("MYSTERY", []) == "MYSTERY"
