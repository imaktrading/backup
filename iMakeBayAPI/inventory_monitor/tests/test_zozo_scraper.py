"""zozo_scraper の parse + 判定 regression (2026-08-10 [IMPLEMENT-GO]).

★1丁目1番地 判定 (窓口 2026-08-10 回答書):
  ① カタログのデータ (公式サイト ld+json) は正しい (窓口 実サンプル対比で確定)
  ② 出品くん (監視くん) の引き方は canonical KEY (ld+json sku) のみ = 正
  → 「①も②も正しい」の状態 (新規実装なので発生源は今ここで作る)。
    PreOrder を InStock に倒す既存誤りは無い (これから新設)。

このテストは以下を回帰ガードする:
  - ld+json の availability から in_stock / excluded / stock_label を導出できる
  - **PreOrder は variation 単位で excluded=True + in_stock=False** (窓口 2026-08-10)
  - 未知 availability (BackOrder 等) は保守的に excluded=True (fail-closed)
  - sku_code は ld+json の sku を **合成せず** そのまま使う (canonical KEY)
  - PreOrder InStock が混在する袴セット型ページで InStock 分は残る (商品単位で弾かない)
  - HTML "sellType":"在庫・予約商品" マーカーの検出
  - オフスクリーン起動時の 2,577 bytes 弾き検知 (小さすぎる response で raise)
  - ZOZO 専用 profile 限定の orphan cleanup (headless 有無を問わず kill)
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from zozo_scraper import (  # noqa: E402
    parse_zozo_html,
    parse_zozo_url,
    _classify_availability,
    _normalize_availability,
    _price_to_int,
    _extract_color_size_from_name,
    _extract_next_data_shelves,
    _select_stale_zozo_pids,
    ZOZO_CHROME_PROFILE_DIR,
)


# ---------------------------------------------------------------------------
# 通常在庫品 fixture (minius / 103638934, 8 SKU 全 InStock)
# ---------------------------------------------------------------------------
FIXTURE_MINIUS = r"""<!doctype html>
<html>
<head>
<script type="application/ld+json">
{
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    "itemListElement": []
}
</script>
<script type="application/ld+json">
{
    "@context": "https://schema.org",
    "@type": "ProductGroup",
    "name": "炎炎ノ消防隊 コラボTシャツ",
    "productGroupID": "103638934",
    "url": "https://zozo.jp/shop/minius/goods/103638934/",
    "hasVariant": [
        {"@type": "Product", "sku": "166413955", "name": "炎炎 (ブラック/MEDIUM)",
         "color": "ブラック", "size": "MEDIUM",
         "offers": {"@type": "Offer", "priceCurrency": "JPY", "price": "4950",
                    "availability": "https://schema.org/InStock"}},
        {"@type": "Product", "sku": "166413956", "name": "炎炎 (ブラック/LARGE)",
         "color": "ブラック", "size": "LARGE",
         "offers": {"@type": "Offer", "priceCurrency": "JPY", "price": "4950",
                    "availability": "https://schema.org/InStock"}},
        {"@type": "Product", "sku": "166413957", "name": "炎炎 (ブラック/X-LARGE)",
         "color": "ブラック", "size": "X-LARGE",
         "offers": {"@type": "Offer", "priceCurrency": "JPY", "price": "4950",
                    "availability": "https://schema.org/InStock"}},
        {"@type": "Product", "sku": "166413958", "name": "炎炎 (ブラック/XX-LARGE)",
         "color": "ブラック", "size": "XX-LARGE",
         "offers": {"@type": "Offer", "priceCurrency": "JPY", "price": "4950",
                    "availability": "https://schema.org/InStock"}},
        {"@type": "Product", "sku": "166413959", "name": "炎炎 (ホワイト/MEDIUM)",
         "color": "ホワイト", "size": "MEDIUM",
         "offers": {"@type": "Offer", "priceCurrency": "JPY", "price": "4950",
                    "availability": "https://schema.org/InStock"}},
        {"@type": "Product", "sku": "166413960", "name": "炎炎 (ホワイト/LARGE)",
         "color": "ホワイト", "size": "LARGE",
         "offers": {"@type": "Offer", "priceCurrency": "JPY", "price": "4950",
                    "availability": "https://schema.org/InStock"}},
        {"@type": "Product", "sku": "166413961", "name": "炎炎 (ホワイト/X-LARGE)",
         "color": "ホワイト", "size": "X-LARGE",
         "offers": {"@type": "Offer", "priceCurrency": "JPY", "price": "4950",
                    "availability": "https://schema.org/InStock"}},
        {"@type": "Product", "sku": "166413962", "name": "炎炎 (ホワイト/XX-LARGE)",
         "color": "ホワイト", "size": "XX-LARGE",
         "offers": {"@type": "Offer", "priceCurrency": "JPY", "price": "4950",
                    "availability": "https://schema.org/InStock"}}
    ]
}
</script>
</head>
<body>
<div class="p-goods-information">
    <div data-sellType='"sellType":"在庫商品"'></div>
</div>
</body>
</html>
"""

URL_MINIUS = "https://zozo.jp/shop/minius/goods/103638934/?did=166413955"


# ---------------------------------------------------------------------------
# 予約商品混在 fixture (SOUBIEN 袴4点セット、PreOrder / InStock / OutOfStock 混在)
# ---------------------------------------------------------------------------
FIXTURE_HAKAMA_PREORDER = r"""<!doctype html>
<html><head>
<script type="application/ld+json">
{
    "@context": "https://schema.org",
    "@type": "ProductGroup",
    "name": "袴4点セット 予約",
    "productGroupID": "999999999",
    "hasVariant": [
        {"@type": "Product", "sku": "H001", "name": "袴 (ネイビー/M)",
         "color": "ネイビー", "size": "M",
         "offers": {"@type": "Offer", "priceCurrency": "JPY", "price": "35800",
                    "availability": "https://schema.org/PreOrder"}},
        {"@type": "Product", "sku": "H002", "name": "袴 (ネイビー/L)",
         "color": "ネイビー", "size": "L",
         "offers": {"@type": "Offer", "priceCurrency": "JPY", "price": "35800",
                    "availability": "https://schema.org/InStock"}},
        {"@type": "Product", "sku": "H003", "name": "袴 (グレー/M)",
         "color": "グレー", "size": "M",
         "offers": {"@type": "Offer", "priceCurrency": "JPY", "price": "35800",
                    "availability": "https://schema.org/OutOfStock"}},
        {"@type": "Product", "sku": "H004", "name": "袴 (グレー/L)",
         "color": "グレー", "size": "L",
         "offers": {"@type": "Offer", "priceCurrency": "JPY", "price": "35800",
                    "availability": "https://schema.org/PreOrder"}}
    ]
}
</script>
</head><body>
<div>{"sellType":"在庫・予約商品"}</div>
</body></html>
"""
URL_HAKAMA = "https://zozo.jp/shop/soubien/goods/999999999/"


# ---------------------------------------------------------------------------
# 未知 availability fixture (BackOrder / MadeToOrder / unknown)
# ---------------------------------------------------------------------------
FIXTURE_UNKNOWN_AVAIL = r"""<!doctype html>
<html><body>
<script type="application/ld+json">
{
    "@context": "https://schema.org",
    "@type": "ProductGroup",
    "name": "混在テスト",
    "productGroupID": "888888888",
    "hasVariant": [
        {"@type": "Product", "sku": "U1", "name": "test (BLACK/M)",
         "color": "BLACK", "size": "M",
         "offers": {"@type": "Offer", "priceCurrency": "JPY", "price": "1000",
                    "availability": "https://schema.org/BackOrder"}},
        {"@type": "Product", "sku": "U2", "name": "test (BLACK/L)",
         "color": "BLACK", "size": "L",
         "offers": {"@type": "Offer", "priceCurrency": "JPY", "price": "1000",
                    "availability": "https://schema.org/MadeToOrder"}},
        {"@type": "Product", "sku": "U3", "name": "test (BLACK/XL)",
         "color": "BLACK", "size": "XL",
         "offers": {"@type": "Offer", "priceCurrency": "JPY", "price": "1000",
                    "availability": "https://schema.org/SomethingUnknown"}}
    ]
}
</script>
</body></html>
"""
URL_UNKNOWN = "https://zozo.jp/shop/tester/goods/888888888/"


# ---------------------------------------------------------------------------
# URL パーサ
# ---------------------------------------------------------------------------
def test_parse_zozo_url_extracts_shop_goods_did():
    r = parse_zozo_url("https://zozo.jp/shop/minius/goods/103638934/?did=166413955")
    assert r == {"shop": "minius", "goods_id": "103638934", "did": "166413955"}


def test_parse_zozo_url_without_did_query():
    r = parse_zozo_url("https://zozo.jp/shop/minius/goods/103638934/")
    assert r["shop"] == "minius"
    assert r["goods_id"] == "103638934"
    assert r["did"] == ""


def test_parse_zozo_url_rejects_non_zozo():
    with pytest.raises(ValueError):
        parse_zozo_url("https://uniqlo.com/jp/products/E483933-000")


def test_parse_zozo_url_rejects_root():
    with pytest.raises(ValueError):
        parse_zozo_url("https://zozo.jp/")


def test_parse_zozo_url_supports_trailing_query_hash():
    r = parse_zozo_url(
        "https://zozo.jp/shop/minius/goods/103638934/?did=166413955&utm=xxx#anchor")
    assert r["goods_id"] == "103638934"
    assert r["did"] == "166413955"


def test_parse_zozo_url_rejects_empty():
    with pytest.raises(ValueError):
        parse_zozo_url("")


# ---------------------------------------------------------------------------
# メイン parse: minius (全 InStock, 8 SKU)
# ---------------------------------------------------------------------------
def test_parse_minius_yields_8_skus():
    r = parse_zozo_html(FIXTURE_MINIUS, URL_MINIUS)
    assert r["product_id"] == "103638934"
    assert r["shop"] == "minius"
    assert r["name"] == "炎炎ノ消防隊 コラボTシャツ"
    assert len(r["skus"]) == 8


def test_parse_minius_sku_codes_are_ldjson_canonical():
    """★ sku_code は ld+json の sku を **合成せず** そのまま使う (canonical KEY)."""
    r = parse_zozo_html(FIXTURE_MINIUS, URL_MINIUS)
    codes = sorted([s["sku_code"] for s in r["skus"]])
    assert codes == [
        "166413955", "166413956", "166413957", "166413958",
        "166413959", "166413960", "166413961", "166413962",
    ]
    for s in r["skus"]:
        assert s["l2Id"] == s["sku_code"]
        assert s["communication_code"] == s["sku_code"]


def test_parse_minius_all_in_stock():
    r = parse_zozo_html(FIXTURE_MINIUS, URL_MINIUS)
    for s in r["skus"]:
        assert s["in_stock"] is True
        assert s["excluded"] is False
        assert s["stock_status"] == "InStock"
        assert s["stock_label"] == "在庫あり"
        assert s["quantity"] == 1


def test_parse_minius_price_and_no_list_price():
    """ZOZO は base/promo 区別不能 → U 列 (list_price_jpy) は None (=空欄)."""
    r = parse_zozo_html(FIXTURE_MINIUS, URL_MINIUS)
    for s in r["skus"]:
        assert s["price_jpy"] == 4950
        assert s["promo_price_jpy"] == 4950
        assert s["list_price_jpy"] is None    # ★ 「定価不明」= None


def test_parse_minius_color_size_from_ldjson():
    r = parse_zozo_html(FIXTURE_MINIUS, URL_MINIUS)
    by_sku = {s["sku_code"]: s for s in r["skus"]}
    assert by_sku["166413955"]["color"] == "ブラック"
    assert by_sku["166413955"]["size"] == "MEDIUM"
    assert by_sku["166413959"]["color"] == "ホワイト"
    assert by_sku["166413959"]["size"] == "MEDIUM"


def test_parse_minius_has_preorder_flag_false():
    r = parse_zozo_html(FIXTURE_MINIUS, URL_MINIUS)
    assert r["has_preorder_flag"] is False


# ---------------------------------------------------------------------------
# 予約商品混在 (袴セット): PreOrder は variation 単位で除外、InStock 分は残す
# ---------------------------------------------------------------------------
def test_parse_hakama_yields_all_4_variations():
    """商品単位で弾かない: PreOrder 混在でも InStock 変種は必ず抽出される."""
    r = parse_zozo_html(FIXTURE_HAKAMA_PREORDER, URL_HAKAMA)
    assert len(r["skus"]) == 4


def test_parse_hakama_preorder_variations_are_excluded_not_in_stock():
    """★§完成条件 (窓口): PreOrder は in_stock=False + excluded=True."""
    r = parse_zozo_html(FIXTURE_HAKAMA_PREORDER, URL_HAKAMA)
    by_sku = {s["sku_code"]: s for s in r["skus"]}
    # PreOrder 2 件
    for sku_id in ("H001", "H004"):
        assert by_sku[sku_id]["in_stock"] is False
        assert by_sku[sku_id]["excluded"] is True
        assert by_sku[sku_id]["stock_status"] == "PreOrder"
        assert by_sku[sku_id]["stock_label"] == "予約商品"
        assert by_sku[sku_id]["quantity"] == 0


def test_parse_hakama_instock_variation_survives():
    """★商品単位で弾いてはいけない: 在庫あり (H002) が残る."""
    r = parse_zozo_html(FIXTURE_HAKAMA_PREORDER, URL_HAKAMA)
    by_sku = {s["sku_code"]: s for s in r["skus"]}
    assert by_sku["H002"]["in_stock"] is True
    assert by_sku["H002"]["excluded"] is False
    assert by_sku["H002"]["stock_label"] == "在庫あり"


def test_parse_hakama_outofstock_variation_is_out_but_not_excluded():
    """OutOfStock は「除外」ではなく単に「在庫なし」 (再入荷可能性)."""
    r = parse_zozo_html(FIXTURE_HAKAMA_PREORDER, URL_HAKAMA)
    by_sku = {s["sku_code"]: s for s in r["skus"]}
    assert by_sku["H003"]["in_stock"] is False
    assert by_sku["H003"]["excluded"] is False
    assert by_sku["H003"]["stock_status"] == "OutOfStock"


def test_parse_hakama_has_preorder_flag_true():
    """HTML "sellType":"在庫・予約商品" は商品全体のマーカー、判定補助として保持."""
    r = parse_zozo_html(FIXTURE_HAKAMA_PREORDER, URL_HAKAMA)
    assert r["has_preorder_flag"] is True


# ---------------------------------------------------------------------------
# 未知 availability の fail-closed (BackOrder / MadeToOrder / 未知値)
# ---------------------------------------------------------------------------
def test_parse_unknown_availability_is_fail_closed():
    """★fail-closed: 未知値・BackOrder・MadeToOrder は excluded=True + in_stock=False."""
    r = parse_zozo_html(FIXTURE_UNKNOWN_AVAIL, URL_UNKNOWN)
    for s in r["skus"]:
        assert s["in_stock"] is False, f"{s['sku_code']} を InStock に倒すな (fail-closed)"
        assert s["excluded"] is True, f"{s['sku_code']} は excluded=True (fail-closed)"


def test_parse_backorder_and_madetoorder_have_recognizable_labels():
    r = parse_zozo_html(FIXTURE_UNKNOWN_AVAIL, URL_UNKNOWN)
    by_sku = {s["sku_code"]: s for s in r["skus"]}
    assert by_sku["U1"]["stock_status"] == "BackOrder"
    assert by_sku["U2"]["stock_status"] == "MadeToOrder"
    # 未知値も 判定不能 として明示
    assert by_sku["U3"]["stock_label"] == "判定不能"


# ---------------------------------------------------------------------------
# ld+json 欠損時は例外 (fail-closed: 「取得したが 0 件」を成功にしない)
# ---------------------------------------------------------------------------
def test_parse_raises_when_no_ldjson_block():
    with pytest.raises(ValueError):
        parse_zozo_html("<html><body>no ldjson here</body></html>",
                        "https://zozo.jp/shop/x/goods/1/")


def test_parse_raises_when_ldjson_has_no_variations():
    html = r"""<script type="application/ld+json">
    {"@type":"BreadcrumbList","itemListElement":[]}</script>"""
    with pytest.raises(ValueError):
        parse_zozo_html(html, "https://zozo.jp/shop/x/goods/1/")


# ---------------------------------------------------------------------------
# _classify_availability / _normalize_availability
# ---------------------------------------------------------------------------
def test_normalize_availability_strips_schema_prefix():
    assert _normalize_availability("https://schema.org/InStock") == "InStock"
    assert _normalize_availability("http://schema.org/PreOrder") == "PreOrder"
    assert _normalize_availability("https://schema.org/InStock/") == "InStock"
    assert _normalize_availability(None) == ""
    assert _normalize_availability("") == ""


def test_classify_availability_instock():
    r = _classify_availability("https://schema.org/InStock")
    assert r["in_stock"] is True
    assert r["excluded"] is False
    assert r["label"] == "在庫あり"


def test_classify_availability_preorder_is_excluded():
    """★§完成条件: PreOrder は必ず excluded=True + in_stock=False."""
    r = _classify_availability("https://schema.org/PreOrder")
    assert r["in_stock"] is False
    assert r["excluded"] is True
    assert r["label"] == "予約商品"


def test_classify_availability_outofstock_is_not_excluded():
    r = _classify_availability("https://schema.org/OutOfStock")
    assert r["in_stock"] is False
    assert r["excluded"] is False


def test_classify_availability_unknown_is_fail_closed():
    """★未知値は保守的に in_stock=False + excluded=True."""
    r = _classify_availability("https://schema.org/SomethingWeird")
    assert r["in_stock"] is False
    assert r["excluded"] is True


def test_classify_availability_none_is_fail_closed():
    r = _classify_availability(None)
    assert r["in_stock"] is False
    assert r["excluded"] is True


# ---------------------------------------------------------------------------
# _price_to_int (欠損は None、"0 円と誤認しない")
# ---------------------------------------------------------------------------
def test_price_to_int_from_string_number():
    assert _price_to_int("4950") == 4950
    assert _price_to_int("4,950") == 4950
    assert _price_to_int("4950.0") == 4950


def test_price_to_int_from_int():
    assert _price_to_int(4950) == 4950


def test_price_to_int_from_empty_or_none_is_none():
    assert _price_to_int("") is None
    assert _price_to_int(None) is None


def test_price_to_int_from_invalid_is_none():
    assert _price_to_int("N/A") is None


# ---------------------------------------------------------------------------
# _extract_color_size_from_name (Product.color/.size 欠損時のフォールバック)
# ---------------------------------------------------------------------------
def test_extract_color_size_parens_pattern():
    assert _extract_color_size_from_name("商品名 (ブラック/MEDIUM)") == ("ブラック", "MEDIUM")


def test_extract_color_size_brackets_pattern():
    assert _extract_color_size_from_name("商品名 [BLACK][M]") == ("BLACK", "M")


def test_extract_color_size_missing_returns_empty():
    """マッチしなければ ("", "") を返す (捏造しない)."""
    assert _extract_color_size_from_name("シンプルなタイトル") == ("", "")


# ---------------------------------------------------------------------------
# orphan chrome cleanup: ZOZO 専用 profile 限定 + headless 有無を問わず kill
# ---------------------------------------------------------------------------
MINE_ZOZO = ZOZO_CHROME_PROFILE_DIR
OTHER_MERCARI = r"C:\Users\imax2\local_data\iMakMercari\chrome_profile"


def _p(pid, name, cmd="", ppid=1):
    return {"ProcessId": pid, "ParentProcessId": ppid, "Name": name, "CommandLine": cmd}


def test_zozo_cleanup_kills_own_non_headless_chrome():
    """★窓口指示: ZOZO は非headless 固定なので、非headless でも自 profile なら kill."""
    procs = [_p(10, "chrome.exe", f'chrome.exe --user-data-dir="{MINE_ZOZO}"'),
             _p(11, "chrome.exe", f'chrome.exe --user-data-dir={MINE_ZOZO} --lang=ja-JP')]
    assert sorted(_select_stale_zozo_pids(procs, MINE_ZOZO)) == [10, 11]


def test_zozo_cleanup_also_kills_headless_own_profile():
    """headless で ZOZO profile を使うことは通常無いが、あれば kill (対称性)."""
    procs = [_p(20, "chrome.exe", f'chrome.exe --headless --user-data-dir={MINE_ZOZO}')]
    assert _select_stale_zozo_pids(procs, MINE_ZOZO) == [20]


def test_zozo_cleanup_keeps_other_project_chrome():
    """★越境防止: mercari profile 等の他プロジェクト chrome は残す."""
    procs = [_p(30, "chrome.exe", f'chrome.exe --headless --user-data-dir="{OTHER_MERCARI}"'),
             _p(31, "chrome.exe", "chrome.exe")]   # profile 指定なし = 誰のか不明
    assert _select_stale_zozo_pids(procs, MINE_ZOZO) == []


def test_zozo_cleanup_keeps_user_normal_browser():
    """profile を指定していない = 通常ブラウザは絶対に触らない."""
    procs = [_p(40, "chrome.exe", "chrome.exe")]
    assert _select_stale_zozo_pids(procs, MINE_ZOZO) == []


def test_zozo_cleanup_orphan_driver_only():
    """親が死んでいる driver だけ kill (稼働中は残す)."""
    procs = [_p(1000, "python.exe"),
             _p(50, "undetected_chromedriver.exe", "uc", ppid=1000),   # 稼働中
             _p(51, "undetected_chromedriver.exe", "uc", ppid=9999)]   # orphan
    assert _select_stale_zozo_pids(procs, MINE_ZOZO) == [51]


def test_zozo_cleanup_unknown_commandline_not_killed():
    """CommandLine が取れない (権限等) なら触らない = fail-safe."""
    procs = [_p(60, "chrome.exe", None), _p(61, "chrome.exe", "")]
    assert _select_stale_zozo_pids(procs, MINE_ZOZO) == []


def test_zozo_cleanup_self_pid_never_killed():
    procs = [_p(70, "chrome.exe", f'--user-data-dir={MINE_ZOZO}')]
    assert _select_stale_zozo_pids(procs, MINE_ZOZO, self_pid=70) == []


def test_zozo_cleanup_empty_profile_dir_kills_nothing():
    """profile dir が空文字なら 1 つも kill しない (安全側)."""
    procs = [_p(80, "chrome.exe", f'--user-data-dir={MINE_ZOZO}')]
    assert _select_stale_zozo_pids(procs, "") == []


def test_zozo_profile_dir_is_dedicated_not_shared_with_mercari():
    """★窓口 [IMPLEMENT-GO] 条件2: mercari profile 共有禁止."""
    assert ZOZO_CHROME_PROFILE_DIR != r"C:\Users\imax2\local_data\iMakMercari\chrome_profile"
    assert "iMakZozo" in ZOZO_CHROME_PROFILE_DIR


# ---------------------------------------------------------------------------
# __NEXT_DATA__ shelves — ZOZO の実 HTML では size が ld+json に無い (2026-08-10 実測)
# → __NEXT_DATA__.props.pageProps.frontServerResult.goodsShelfInfo.shelves が canonical source。
#   ★1丁目1番地 判定: ①データは正しい (shelves で size 提供) / ②引き方が誤り (parser が
#     shelves を無視して ld+json 単独で size="") → ②を修正 (カタログ = ZOZO には依頼を出さない)。
# ---------------------------------------------------------------------------
_REAL_NEXT_DATA_HTML = r"""<!doctype html>
<html><head>
<script type="application/ld+json">{"@type":"BreadcrumbList","itemListElement":[]}</script>
<script type="application/ld+json">
[{"@context":"https://schema.org","@type":"Product","sku":"166413955",
  "name":"炎炎 コラボTシャツ","color":"ブラック","brand":{"@type":"Brand","name":"minius"},
  "offers":{"@type":"Offer","priceCurrency":"JPY","price":"4950",
            "availability":"https://schema.org/InStock"}}]
</script>
<script type="application/ld+json">
[{"@context":"https://schema.org","@type":"Product","sku":"166413959",
  "name":"炎炎 コラボTシャツ","color":"ホワイト","brand":{"@type":"Brand","name":"minius"},
  "offers":{"@type":"Offer","priceCurrency":"JPY","price":"4950",
            "availability":"https://schema.org/InStock"}}]
</script>
<script id="__NEXT_DATA__" type="application/json">
{"props":{"pageProps":{"frontServerResult":{"goodsShelfInfo":{"shelves":[
    {"shelfId":137279390,"goodsDetailId":166413955,"sizeId":2,"sizeShortName":"M",
     "sizeName":"MEDIUM","colorName":"ブラック","colorId":8,
     "captionType":"INSTOCK","stockQuantity":1,"reserveDeliveryDatetime":null},
    {"shelfId":137279397,"goodsDetailId":166413959,"sizeId":2,"sizeShortName":"M",
     "sizeName":"MEDIUM","colorName":"ホワイト","colorId":1,
     "captionType":"INSTOCK","stockQuantity":2,"reserveDeliveryDatetime":null}
]}}}}}
</script>
</head><body></body></html>
"""
_REAL_URL = "https://zozo.jp/shop/minius/goods/103638934/"


def test_extract_next_data_shelves_keys_by_goods_detail_id():
    """shelves は goodsDetailId (str) をキーに参照できる (= ld+json sku と一致)."""
    shelves = _extract_next_data_shelves(_REAL_NEXT_DATA_HTML)
    assert set(shelves.keys()) == {"166413955", "166413959"}
    assert shelves["166413955"]["sizeShortName"] == "M"
    assert shelves["166413955"]["colorName"] == "ブラック"


def test_extract_next_data_shelves_returns_empty_when_missing():
    """__NEXT_DATA__ が無い/壊れている → 空 dict (捏造しない・落とさない)."""
    assert _extract_next_data_shelves("<html><body></body></html>") == {}
    assert _extract_next_data_shelves(
        '<script id="__NEXT_DATA__" type="application/json">not json</script>'
    ) == {}
    # 期待経路が無い形の JSON も空 dict
    assert _extract_next_data_shelves(
        '<script id="__NEXT_DATA__" type="application/json">{"props":{}}</script>'
    ) == {}


def test_parse_zozo_html_populates_size_from_shelves():
    """★実 HTML 型 (size が ld+json に無い) — shelves から size 補完で "" にならない."""
    r = parse_zozo_html(_REAL_NEXT_DATA_HTML, _REAL_URL)
    by_sku = {s["sku_code"]: s for s in r["skus"]}
    assert by_sku["166413955"]["size"] == "M"
    assert by_sku["166413955"]["color"] == "ブラック"
    assert by_sku["166413959"]["size"] == "M"
    assert by_sku["166413959"]["color"] == "ホワイト"


def test_parse_zozo_html_ldjson_size_takes_precedence_over_shelves():
    """ld+json の Product.size があればそちらを優先 (fixture 互換性の担保)."""
    # FIXTURE_MINIUS は Product.size を持つので、shelves があっても ld+json 側が勝つべき
    r = parse_zozo_html(FIXTURE_MINIUS, URL_MINIUS)
    by_sku = {s["sku_code"]: s for s in r["skus"]}
    # fixture の ld+json は "MEDIUM"/"LARGE"/... フル名
    assert by_sku["166413955"]["size"] == "MEDIUM"
    assert by_sku["166413956"]["size"] == "LARGE"
