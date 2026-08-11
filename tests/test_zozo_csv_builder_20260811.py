"""Regression: 2026-08-11 — ZOZO 出品 CSV POC (scraper + csv_builder, minius 1ブランド).

依頼書: C:/dev/iMak_data/harvest/requests/2026-08-10_zozo_preorder_detection_confirmed_response.md

観点:
  - scraper.parse_zozo_html: ld+json + __NEXT_DATA__ shelves parse
  - availability 分類 (InStock / PreOrder / OutOfStock / 未知)
  - PreOrder は variation 単位で excluded=True (商品単位で reject しない)
  - 色ごとに 1 listing (multi-color URL)、Size を variation 軸
  - CSV 構造 (parent + children、header 幅一致、SKU=UUID)
  - 予約レポートは CSV 列でなく別ファイル (窓口指示)
  - minius 以外の shop は build_csv で拒否
"""
from __future__ import annotations

import csv
import io
import os
import re
import sys
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_MERCARI = _ROOT / "iMakMercari"
_API = _ROOT / "iMakeBayAPI"
for _p in (_MERCARI, _API):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# import 順の副作用回避: 他テストが sys.path から iMakMercari を落とすため先読み
import zozo_scraper       # noqa: E402,F401
import zozo_csv_builder   # noqa: E402,F401

# ★ import 完了後、iMakMercari を sys.path から除去 (name shadowing 防止).
# iMakMercari/check_csv.py と iMakeBayAPI/check_csv.py が同名で共存しており、
# insert(0) を残すと後続の test_phase_d_cache_sharing の import check_csv が
# iMakMercari 側を掴んで market_gate cache 共有が壊れる (2026-08-11 実測)。
# zozo_scraper / zozo_csv_builder は sys.modules にキャッシュ済のため以後の参照は path 不要。
while str(_MERCARI) in sys.path:
    sys.path.remove(str(_MERCARI))


# ============================================================================
# HTML fixtures (窓口 2026-08-10 実測 minius/103638934 を最小再構成)
# 実測: 色2 (ブラック/ホワイト) × サイズ4 (MEDIUM/LARGE/X-LARGE/XX-LARGE) = 8 SKU
#       全 InStock ¥4950 / brand=minius
# ★ ZOZO の ld+json Product には size フィールドが空 = __NEXT_DATA__ shelves で補完
# ============================================================================
_HTML_ALL_INSTOCK = '''<html><head></head><body>
<script type="application/ld+json">
[{"@context":"https://schema.org/","@type":"ProductGroup",
"name":"炎炎ノ消防隊 グラフィックTシャツ",
"description":"炎炎ノ消防隊とのコラボレーションTシャツです",
"url":"https://zozo.jp/shop/minius/goods/103638934/",
"brand":{"@type":"Brand","name":"minius"},
"productGroupID":"103638934",
"material":"綿 100%",
"image":["https://c.imgz.jp/i1.jpg","https://c.imgz.jp/i2.jpg"],
"hasVariant":[
  {"@type":"Product","sku":"166413952","color":"","offers":{"@type":"Offer","availability":"https://schema.org/InStock","price":"4950","priceCurrency":"JPY"}},
  {"@type":"Product","sku":"166413953","color":"","offers":{"@type":"Offer","availability":"https://schema.org/InStock","price":"4950","priceCurrency":"JPY"}},
  {"@type":"Product","sku":"166413954","color":"","offers":{"@type":"Offer","availability":"https://schema.org/InStock","price":"4950","priceCurrency":"JPY"}},
  {"@type":"Product","sku":"166413955","color":"","offers":{"@type":"Offer","availability":"https://schema.org/InStock","price":"4950","priceCurrency":"JPY"}},
  {"@type":"Product","sku":"166413956","color":"","offers":{"@type":"Offer","availability":"https://schema.org/InStock","price":"4950","priceCurrency":"JPY"}},
  {"@type":"Product","sku":"166413957","color":"","offers":{"@type":"Offer","availability":"https://schema.org/InStock","price":"4950","priceCurrency":"JPY"}},
  {"@type":"Product","sku":"166413958","color":"","offers":{"@type":"Offer","availability":"https://schema.org/InStock","price":"4950","priceCurrency":"JPY"}},
  {"@type":"Product","sku":"166413959","color":"","offers":{"@type":"Offer","availability":"https://schema.org/InStock","price":"4950","priceCurrency":"JPY"}}
]}]
</script>
<script id="__NEXT_DATA__" type="application/json">
{"props":{"pageProps":{"frontServerResult":{"goodsShelfInfo":{"shelves":[
  {"goodsDetailId":166413952,"sizeShortName":"MEDIUM","colorName":"ブラック","captionType":"INSTOCK","stockQuantity":5},
  {"goodsDetailId":166413953,"sizeShortName":"LARGE","colorName":"ブラック","captionType":"INSTOCK","stockQuantity":3},
  {"goodsDetailId":166413954,"sizeShortName":"X-LARGE","colorName":"ブラック","captionType":"INSTOCK","stockQuantity":2},
  {"goodsDetailId":166413955,"sizeShortName":"XX-LARGE","colorName":"ブラック","captionType":"INSTOCK","stockQuantity":1},
  {"goodsDetailId":166413956,"sizeShortName":"MEDIUM","colorName":"ホワイト","captionType":"INSTOCK","stockQuantity":4},
  {"goodsDetailId":166413957,"sizeShortName":"LARGE","colorName":"ホワイト","captionType":"INSTOCK","stockQuantity":3},
  {"goodsDetailId":166413958,"sizeShortName":"X-LARGE","colorName":"ホワイト","captionType":"INSTOCK","stockQuantity":2},
  {"goodsDetailId":166413959,"sizeShortName":"XX-LARGE","colorName":"ホワイト","captionType":"INSTOCK","stockQuantity":1}
]}}}}}
</script>
</body></html>
'''

# --- PreOrder 混在 fixture (窓口 2026-08-10 対比のうち予約側と同構造) ---
_HTML_PREORDER_MIXED = '''<html><head></head><body>
<script type="application/ld+json">
[{"@context":"https://schema.org/","@type":"ProductGroup",
"name":"予約商品テスト",
"description":"予約と在庫が混在する fixture",
"url":"https://zozo.jp/shop/minius/goods/103999999/",
"brand":{"@type":"Brand","name":"minius"},
"productGroupID":"103999999",
"image":["https://c.imgz.jp/pre1.jpg"],
"hasVariant":[
  {"@type":"Product","sku":"200000001","offers":{"availability":"https://schema.org/InStock","price":"4950","priceCurrency":"JPY"}},
  {"@type":"Product","sku":"200000002","offers":{"availability":"https://schema.org/PreOrder","price":"4950","priceCurrency":"JPY"}},
  {"@type":"Product","sku":"200000003","offers":{"availability":"https://schema.org/OutOfStock","price":"4950","priceCurrency":"JPY"}},
  {"@type":"Product","sku":"200000004","offers":{"availability":"https://schema.org/MadeToOrder","price":"4950","priceCurrency":"JPY"}}
]}]
</script>
<script id="__NEXT_DATA__" type="application/json">
{"props":{"pageProps":{"frontServerResult":{"goodsShelfInfo":{"shelves":[
  {"goodsDetailId":200000001,"sizeShortName":"MEDIUM","colorName":"ブラック"},
  {"goodsDetailId":200000002,"sizeShortName":"LARGE","colorName":"ブラック"},
  {"goodsDetailId":200000003,"sizeShortName":"X-LARGE","colorName":"ブラック"},
  {"goodsDetailId":200000004,"sizeShortName":"XX-LARGE","colorName":"ブラック"}
]}}}}}
</script>
<div>"sellType":"在庫・予約商品"</div>
</body></html>
'''

# --- 別ブランド (SOUBIEN 等) fixture (minius 制限テスト用) ---
_HTML_OTHER_SHOP = _HTML_ALL_INSTOCK.replace(
    "https://zozo.jp/shop/minius/goods/103638934/",
    "https://zozo.jp/shop/soubien/goods/103638934/",
)

# --- ld+json 欠損 fixture ---
_HTML_NO_LDJSON = "<html><body><p>empty</p></body></html>"


# ============================================================================
# scraper: URL パーサ
# ============================================================================
class TestParseUrl:
    def test_valid_minius_url(self):
        info = zozo_scraper.parse_zozo_url(
            "https://zozo.jp/shop/minius/goods/103638934/?did=166413955"
        )
        assert info["shop"] == "minius"
        assert info["goods_id"] == "103638934"
        assert info["did"] == "166413955"

    def test_valid_url_without_did(self):
        info = zozo_scraper.parse_zozo_url(
            "https://zozo.jp/shop/minius/goods/103638934/"
        )
        assert info["shop"] == "minius"
        assert info["goods_id"] == "103638934"
        assert info["did"] == ""

    def test_empty_url_raises(self):
        with pytest.raises(ValueError, match="URL が空"):
            zozo_scraper.parse_zozo_url("")

    def test_non_goods_url_raises(self):
        with pytest.raises(ValueError, match="ZOZO goods URL 形式"):
            zozo_scraper.parse_zozo_url("https://zozo.jp/shop/minius/")


# ============================================================================
# scraper: availability 分類
# ============================================================================
class TestAvailabilityClassify:
    def test_instock(self):
        r = zozo_scraper._classify_availability("https://schema.org/InStock")
        assert r["in_stock"] is True
        assert r["excluded"] is False
        assert r["raw"] == "InStock"

    def test_preorder_is_excluded_variation_level(self):
        """PreOrder は excluded=True (variation 単位で CSV から落とす). in_stock=False."""
        r = zozo_scraper._classify_availability("https://schema.org/PreOrder")
        assert r["in_stock"] is False
        assert r["excluded"] is True
        assert r["label"] == "予約商品"

    def test_madetoorder_is_excluded(self):
        r = zozo_scraper._classify_availability("https://schema.org/MadeToOrder")
        assert r["excluded"] is True

    def test_outofstock_not_excluded(self):
        """OutOfStock は在庫戻れば買えるので excluded=False (単に在庫なし)."""
        r = zozo_scraper._classify_availability("https://schema.org/OutOfStock")
        assert r["in_stock"] is False
        assert r["excluded"] is False

    def test_unknown_availability_is_failclosed(self):
        """未知値は fail-closed (excluded=True) — 誤出品 BAN リスク回避."""
        r = zozo_scraper._classify_availability("https://schema.org/BogusValue")
        assert r["in_stock"] is False
        assert r["excluded"] is True

    def test_none_availability_is_failclosed(self):
        r = zozo_scraper._classify_availability(None)
        assert r["in_stock"] is False
        assert r["excluded"] is True


# ============================================================================
# scraper: HTML parse (fixture)
# ============================================================================
class TestParseHtml:
    def test_all_instock_extracts_8_skus(self):
        p = zozo_scraper.parse_zozo_html(
            _HTML_ALL_INSTOCK, "https://zozo.jp/shop/minius/goods/103638934/"
        )
        assert p.goods_id == "103638934"
        assert p.shop == "minius"
        assert p.name_jp == "炎炎ノ消防隊 グラフィックTシャツ"
        assert p.brand_jp == "minius"
        assert p.material_jp == "綿 100%"
        assert len(p.skus) == 8
        assert all(s.in_stock for s in p.skus)
        assert all(not s.excluded for s in p.skus)
        assert all(s.price_jpy == 4950 for s in p.skus)

    def test_size_color_filled_from_next_data(self):
        """ZOZO の ld+json Product には size 無し → __NEXT_DATA__ shelves で補完."""
        p = zozo_scraper.parse_zozo_html(
            _HTML_ALL_INSTOCK, "https://zozo.jp/shop/minius/goods/103638934/"
        )
        colors = {s.color for s in p.skus}
        sizes = {s.size for s in p.skus}
        assert colors == {"ブラック", "ホワイト"}
        assert sizes == {"MEDIUM", "LARGE", "X-LARGE", "XX-LARGE"}

    def test_preorder_flag_and_excluded_variations(self):
        p = zozo_scraper.parse_zozo_html(
            _HTML_PREORDER_MIXED, "https://zozo.jp/shop/minius/goods/103999999/"
        )
        assert p.has_preorder_flag is True
        # 4 SKU中 InStock 1件のみ (残 3件は PreOrder/OutOfStock/MadeToOrder)
        instock = [s for s in p.skus if s.in_stock]
        excluded = [s for s in p.skus if s.excluded]
        assert len(instock) == 1
        # excluded = PreOrder + MadeToOrder (OutOfStock は excluded=False)
        assert len(excluded) == 2

    def test_no_ldjson_raises(self):
        with pytest.raises(ValueError, match="ld\\+json"):
            zozo_scraper.parse_zozo_html(
                _HTML_NO_LDJSON, "https://zozo.jp/shop/minius/goods/103638934/"
            )

    def test_images_extracted(self):
        p = zozo_scraper.parse_zozo_html(
            _HTML_ALL_INSTOCK, "https://zozo.jp/shop/minius/goods/103638934/"
        )
        assert p.image_urls == ["https://c.imgz.jp/i1.jpg", "https://c.imgz.jp/i2.jpg"]


# ============================================================================
# scraper: orphan cleanup 選択ロジック (副作用なしテスト)
# ============================================================================
class TestOrphanSelection:
    _PROFILE = r"C:\Users\imax2\local_data\iMakZozo\chrome_profile"

    def test_chrome_with_zozo_profile_selected_regardless_of_headless(self):
        procs = [
            {"ProcessId": 100, "ParentProcessId": 1, "Name": "chrome.exe",
             "CommandLine": f'"chrome" --user-data-dir="{self._PROFILE}" --other'},
            {"ProcessId": 101, "ParentProcessId": 1, "Name": "chrome.exe",
             "CommandLine": f'"chrome" --headless=new --user-data-dir="{self._PROFILE}"'},
        ]
        pids = zozo_scraper._select_stale_zozo_pids(procs, self._PROFILE, self_pid=0)
        assert set(pids) == {100, 101}

    def test_chrome_with_other_profile_not_selected(self):
        procs = [
            {"ProcessId": 200, "ParentProcessId": 1, "Name": "chrome.exe",
             "CommandLine": r'"chrome" --user-data-dir="C:\other\path"'},
        ]
        assert zozo_scraper._select_stale_zozo_pids(procs, self._PROFILE, self_pid=0) == []

    def test_missing_commandline_is_failsafe(self):
        procs = [
            {"ProcessId": 300, "ParentProcessId": 1, "Name": "chrome.exe",
             "CommandLine": ""},
        ]
        assert zozo_scraper._select_stale_zozo_pids(procs, self._PROFILE, self_pid=0) == []

    def test_self_pid_not_selected(self):
        procs = [
            {"ProcessId": 999, "ParentProcessId": 1, "Name": "chrome.exe",
             "CommandLine": f'--user-data-dir="{self._PROFILE}"'},
        ]
        assert zozo_scraper._select_stale_zozo_pids(procs, self._PROFILE, self_pid=999) == []

    def test_orphan_driver_selected(self):
        """driver の親が live プロセス集合に居なければ orphan."""
        procs = [
            {"ProcessId": 400, "ParentProcessId": 9999, "Name": "undetected_chromedriver.exe",
             "CommandLine": "driver"},
        ]
        pids = zozo_scraper._select_stale_zozo_pids(procs, self._PROFILE, self_pid=0)
        assert pids == [400]


# ============================================================================
# csv_builder: 送料 / 価格
# ============================================================================
class TestProcurementShipping:
    def test_below_threshold_adds_330(self):
        assert zozo_csv_builder.procurement_shipping(3299) == 330

    def test_at_threshold_free(self):
        assert zozo_csv_builder.procurement_shipping(3300) == 0

    def test_above_threshold_free(self):
        assert zozo_csv_builder.procurement_shipping(4950) == 0

    def test_zero_adds_330(self):
        assert zozo_csv_builder.procurement_shipping(0) == 330

    def test_compute_listing_price_passes_cost_plus_shipping(self):
        """cost = 商品代 + 仕入送料 が pricing_engine に渡る (¥4,950 は無料閾値超え)."""
        captured = {}

        def _spy(cost_jpy, median_usd, category):
            captured["cost_jpy"] = cost_jpy
            captured["category"] = category
            return {"price": 42.98, "status": "GO"}

        with patch("pricing_engine.compute_listing_price", side_effect=_spy):
            zozo_csv_builder.compute_listing_price_usd(4950)

        assert captured["cost_jpy"] == 4950  # 送料無料閾値超え
        assert captured["category"] == "Tシャツ(UT)"

    def test_compute_listing_price_low_cost_adds_shipping(self):
        captured = {}

        def _spy(cost_jpy, median_usd, category):
            captured["cost_jpy"] = cost_jpy
            return {"price": 10.98, "status": "GO"}

        with patch("pricing_engine.compute_listing_price", side_effect=_spy):
            zozo_csv_builder.compute_listing_price_usd(2000)

        assert captured["cost_jpy"] == 2330   # 2000 + 330


# ============================================================================
# csv_builder: サイズ / 色 / 素材変換
# ============================================================================
class TestSizeColorMaterial:
    def test_jp_size_to_us_medium_large(self):
        assert zozo_csv_builder.jp_size_to_us("MEDIUM") == "S"
        assert zozo_csv_builder.jp_size_to_us("LARGE") == "M"
        assert zozo_csv_builder.jp_size_to_us("X-LARGE") == "L"
        assert zozo_csv_builder.jp_size_to_us("XX-LARGE") == "XL"

    def test_jp_size_short_form(self):
        assert zozo_csv_builder.jp_size_to_us("M") == "S"
        assert zozo_csv_builder.jp_size_to_us("L") == "M"
        assert zozo_csv_builder.jp_size_to_us("XL") == "L"

    def test_jp_size_unknown_returns_original(self):
        assert zozo_csv_builder.jp_size_to_us("SPECIAL") == "SPECIAL"

    def test_color_jp_to_en_known(self):
        assert zozo_csv_builder.color_jp_to_en("ブラック") == "Black"
        assert zozo_csv_builder.color_jp_to_en("ホワイト") == "White"

    def test_color_jp_to_en_unknown_returns_original(self):
        assert zozo_csv_builder.color_jp_to_en("謎色") == "謎色"

    def test_material_jp_to_en(self):
        assert zozo_csv_builder.material_jp_to_en("綿 100%") == "100% Cotton"
        assert zozo_csv_builder.material_jp_to_en("ポリエステル 65% 綿 35%") == "65% Polyester, 35% Cotton"

    def test_primary_material_biggest(self):
        assert zozo_csv_builder.primary_material_en("ポリエステル 65% 綿 35%") == "Polyester"
        assert zozo_csv_builder.primary_material_en("") == "Cotton"  # fallback


# ============================================================================
# csv_builder: 色ごとのグルーピング (excluded を落とす)
# ============================================================================
class TestGroupSkusByColor:
    def test_multi_color_grouped(self):
        p = zozo_scraper.parse_zozo_html(
            _HTML_ALL_INSTOCK, "https://zozo.jp/shop/minius/goods/103638934/"
        )
        groups = zozo_csv_builder.group_skus_by_color(p.skus)
        assert set(groups.keys()) == {"ブラック", "ホワイト"}
        assert len(groups["ブラック"]) == 4
        assert len(groups["ホワイト"]) == 4

    def test_preorder_excluded_from_groups(self):
        p = zozo_scraper.parse_zozo_html(
            _HTML_PREORDER_MIXED, "https://zozo.jp/shop/minius/goods/103999999/"
        )
        groups = zozo_csv_builder.group_skus_by_color(p.skus)
        total = sum(len(v) for v in groups.values())
        assert total == 1  # 4 SKU中 InStock 1件のみ


# ============================================================================
# csv_builder: 予約レポート (窓口指示: CSV に列を足さない)
# ============================================================================
class TestPreorderReport:
    def test_report_generated_when_excluded_present(self):
        p = zozo_scraper.parse_zozo_html(
            _HTML_PREORDER_MIXED, "https://zozo.jp/shop/minius/goods/103999999/"
        )
        report = zozo_csv_builder.build_preorder_report(p)
        assert "予約 variation" in report
        assert "103999999" in report
        # 除外行が入っている (PreOrder + MadeToOrder)
        assert "PreOrder" in report
        assert "MadeToOrder" in report

    def test_report_empty_when_all_instock(self):
        p = zozo_scraper.parse_zozo_html(
            _HTML_ALL_INSTOCK, "https://zozo.jp/shop/minius/goods/103638934/"
        )
        # 全 InStock + preorder_flag 無し → 空文字
        assert zozo_csv_builder.build_preorder_report(p) == ""

    def test_csv_headers_do_not_include_preorder_flag(self):
        """CSV に列を足さない (窓口指示)。CSV_HEADERS に予約フラグ列が無いこと."""
        headers = zozo_csv_builder.CSV_HEADERS
        assert not any("preorder" in h.lower() for h in headers)
        assert not any("予約" in h for h in headers)


# ============================================================================
# csv_builder: parent/variation 行の構造
# ============================================================================
class TestBuilderRows:
    def _mk_product(self):
        return zozo_scraper.parse_zozo_html(
            _HTML_ALL_INSTOCK, "https://zozo.jp/shop/minius/goods/103638934/"
        )

    def test_parent_row_width_matches_headers(self):
        p = self._mk_product()
        groups = zozo_csv_builder.group_skus_by_color(p.skus)
        sku_group = groups["ブラック"]
        row = zozo_csv_builder.build_parent_row(
            p, "ブラック", sku_group, 42.98, "DDP-40-60", "parent-sku",
        )
        assert len(row) == len(zozo_csv_builder.CSV_HEADERS)

    def test_child_row_width_matches_headers(self):
        p = self._mk_product()
        groups = zozo_csv_builder.group_skus_by_color(p.skus)
        sku_group = groups["ブラック"]
        rows = zozo_csv_builder.build_variation_rows(sku_group, 42.98, "parent-sku")
        assert len(rows) == len(sku_group)
        for r in rows:
            assert len(r) == len(zozo_csv_builder.CSV_HEADERS)

    def test_child_sku_is_uuid_and_unique(self):
        p = self._mk_product()
        groups = zozo_csv_builder.group_skus_by_color(p.skus)
        rows = zozo_csv_builder.build_variation_rows(groups["ブラック"], 42.98, "parent")
        idx_sku = zozo_csv_builder.CSV_HEADERS.index("CustomLabel")
        skus = [r[idx_sku] for r in rows]
        assert len(set(skus)) == len(skus)
        for s in skus:
            assert re.match(r"^[0-9a-f]{8}-[0-9a-f]{4}-", s), f"expected UUID, got {s}"

    def test_child_size_column_has_us_jp_pair(self):
        p = self._mk_product()
        groups = zozo_csv_builder.group_skus_by_color(p.skus)
        rows = zozo_csv_builder.build_variation_rows(groups["ブラック"], 42.98, "parent")
        idx_size = zozo_csv_builder.CSV_HEADERS.index("C:Size")
        size_vals = {r[idx_size] for r in rows}
        # MEDIUM→S / LARGE→M / X-LARGE→L / XX-LARGE→XL
        assert "S (JP MEDIUM)" in size_vals
        assert "M (JP LARGE)" in size_vals
        assert "L (JP X-LARGE)" in size_vals
        assert "XL (JP XX-LARGE)" in size_vals

    def test_parent_brand_is_minius(self):
        p = self._mk_product()
        groups = zozo_csv_builder.group_skus_by_color(p.skus)
        row = zozo_csv_builder.build_parent_row(
            p, "ブラック", groups["ブラック"], 42.98, "DDP-40-60", "parent-sku",
        )
        idx_brand = zozo_csv_builder.CSV_HEADERS.index("C:Brand")
        assert row[idx_brand] == "minius"

    def test_parent_pic_url_uses_ldjson_images(self):
        p = self._mk_product()
        groups = zozo_csv_builder.group_skus_by_color(p.skus)
        row = zozo_csv_builder.build_parent_row(
            p, "ブラック", groups["ブラック"], 42.98, "DDP-40-60", "parent-sku",
        )
        idx_pic = zozo_csv_builder.CSV_HEADERS.index("PicURL")
        assert "https://c.imgz.jp/i1.jpg" in row[idx_pic]
        assert "|" in row[idx_pic]  # 複数画像は pipe 区切り


# ============================================================================
# E2E: build_csv 全体
# ============================================================================
class TestBuildCsvE2E:
    def _patch_fetch(self, monkeypatch, html):
        def _fake_fetch(url, driver=None):
            return zozo_scraper.parse_zozo_html(html, url)
        monkeypatch.setattr(zozo_csv_builder, "fetch_product", _fake_fetch)

    def test_e2e_all_instock_writes_2_listings(self, monkeypatch, tmp_path):
        self._patch_fetch(monkeypatch, _HTML_ALL_INSTOCK)
        out = tmp_path / "out.csv"
        result = zozo_csv_builder.build_csv(
            "https://zozo.jp/shop/minius/goods/103638934/",
            out_path=str(out),
        )
        assert result["listings"] == 2  # 色2
        assert result["excluded"] == 0
        assert result["report_path"] is None  # 予約無し → レポート無し

        with open(out, encoding="utf-8") as f:
            rows = list(csv.reader(f))
        # 1 header + 2 parents + 8 children (4サイズ × 2色) = 11 行
        assert len(rows) == 1 + 2 + 8

    def test_e2e_preorder_mixed_excludes_and_writes_report(self, monkeypatch, tmp_path):
        self._patch_fetch(monkeypatch, _HTML_PREORDER_MIXED)
        out = tmp_path / "out.csv"
        report = tmp_path / "out.md"
        result = zozo_csv_builder.build_csv(
            "https://zozo.jp/shop/minius/goods/103999999/",
            out_path=str(out),
            report_path=str(report),
        )
        # InStock 1件 → 1色 × 1 SKU = 1 listing
        assert result["listings"] == 1
        # PreOrder + MadeToOrder → excluded=True (OutOfStock は excluded=False)
        assert result["excluded"] == 2
        assert result["report_path"] == str(report)
        assert report.exists()
        report_text = report.read_text(encoding="utf-8")
        assert "PreOrder" in report_text
        assert "MadeToOrder" in report_text

    def test_e2e_rejects_non_minius_shop(self, monkeypatch, tmp_path):
        """回答書: 実装は minius 1ブランドだけ. 他 shop は build_csv 拒否."""
        self._patch_fetch(monkeypatch, _HTML_OTHER_SHOP)
        out = tmp_path / "out.csv"
        with pytest.raises(ValueError, match="未許可の shop"):
            zozo_csv_builder.build_csv(
                "https://zozo.jp/shop/soubien/goods/103638934/",
                out_path=str(out),
            )

    def test_e2e_csv_written_utf8_no_bom(self, monkeypatch, tmp_path):
        """CSV は UTF-8 (BOMなし) — CLAUDE.md 共通規約."""
        self._patch_fetch(monkeypatch, _HTML_ALL_INSTOCK)
        out = tmp_path / "out.csv"
        zozo_csv_builder.build_csv(
            "https://zozo.jp/shop/minius/goods/103638934/",
            out_path=str(out),
        )
        raw = out.read_bytes()
        assert not raw.startswith(b"\xef\xbb\xbf"), "BOM が付いている (禁止)"

    def test_e2e_csv_quoting_nonnumeric(self, monkeypatch, tmp_path):
        """csv.QUOTE_NONNUMERIC — 文字列は必ずダブルクォート、数値は生のまま."""
        self._patch_fetch(monkeypatch, _HTML_ALL_INSTOCK)
        out = tmp_path / "out.csv"
        zozo_csv_builder.build_csv(
            "https://zozo.jp/shop/minius/goods/103638934/",
            out_path=str(out),
        )
        text = out.read_text(encoding="utf-8")
        first_line = text.split("\n")[0]
        # ヘッダ全部が引用符付き
        assert first_line.startswith('"')

    def test_e2e_all_excluded_raises(self, monkeypatch, tmp_path):
        """在庫 SKU がゼロなら CSV 出力せずエラー (誤って空 CSV 入稿を防ぐ)."""
        html_all_preorder = _HTML_PREORDER_MIXED.replace(
            '"availability":"https://schema.org/InStock"',
            '"availability":"https://schema.org/PreOrder"'
        )
        self._patch_fetch(monkeypatch, html_all_preorder)
        with pytest.raises(ValueError, match="在庫 SKU がありません"):
            zozo_csv_builder.build_csv(
                "https://zozo.jp/shop/minius/goods/103999999/",
                out_path=str(tmp_path / "out.csv"),
            )


# ============================================================================
# 定数 / 設定の固定化
# ============================================================================
class TestConstants:
    def test_zozo_profile_path_is_dedicated(self):
        """出品側専有 profile (回答書 §profile 排他). mercari profile と別."""
        assert zozo_scraper.ZOZO_CHROME_PROFILE_DIR == (
            r"C:\Users\imax2\local_data\iMakZozo\chrome_profile"
        )
        assert "iMakMercari" not in zozo_scraper.ZOZO_CHROME_PROFILE_DIR

    def test_min_html_bytes_threshold(self):
        """2,577 bytes の bot 弾き値を含む閾値 (5000)."""
        assert zozo_scraper.MIN_HTML_BYTES >= 5000

    def test_allowed_shops_is_minius_only(self):
        """minius 1ブランド限定 (回答書 §決定)."""
        assert zozo_csv_builder.ALLOWED_SHOPS == {"minius"}

    def test_pricing_category_is_tshirt_ut(self):
        """T-shirt = 共通 SSOT のカテゴリ (fvf/shipping 揃う)."""
        assert zozo_csv_builder.PRICING_CATEGORY == "Tシャツ(UT)"

    def test_procurement_shipping_constants(self):
        assert zozo_csv_builder.ZOZO_PROCUREMENT_SHIPPING_JPY == 330
        assert zozo_csv_builder.ZOZO_FREE_SHIPPING_THRESHOLD_JPY == 3300


# ============================================================================
# ヘルパ: name_jp からの推定
# ============================================================================
class TestNameDerivations:
    def test_type_default_tshirt(self):
        assert zozo_csv_builder.derive_type_from_name("炎炎ノ消防隊 グラフィックTシャツ") == "T-Shirt"

    def test_type_hoodie(self):
        assert zozo_csv_builder.derive_type_from_name("XX ジップパーカー") == "Hoodie"

    def test_fit_relaxed_when_big_silhouette(self):
        assert zozo_csv_builder.derive_fit("XX ビッグシルエット Tシャツ") == "Relaxed"

    def test_fit_regular_default(self):
        assert zozo_csv_builder.derive_fit("XX Tシャツ") == "Regular"

    def test_title_under_80_chars(self):
        title = zozo_csv_builder.build_title("minius", "炎炎ノ消防隊 グラフィックTシャツ", "Black")
        assert len(title) <= 80
        assert "minius" in title
        assert "Black" in title
