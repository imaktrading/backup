"""tests for scrapers/amazon_search and amazon_item_detail extensions (Phase 6/11)."""
from __future__ import annotations

from scrapers.amazon_item_detail import (
    GSHOCK_MODEL_IN_TITLE_RE,
    _extract_product_id_estimated_from_title,
)
from scrapers.amazon_search import (
    build_search_url_with_page,
    parse_asin_from_url,
    parse_search_url,
)
from sheet_writer_amazon import build_amazon_tab_name, dedupe_key


# ----------------------------------------------------------------------------
# parse_search_url
# ----------------------------------------------------------------------------
def test_parse_search_url_basic():
    r = parse_search_url("https://www.amazon.co.jp/s?k=G-Shock&rh=n%3A337470011")
    assert r is not None
    assert r["keyword"] == "G-Shock"
    assert r["rh"] == "n:337470011"
    assert r["raw_url"].startswith("https://www.amazon.co.jp/s?")


def test_parse_search_url_invalid_host():
    assert parse_search_url("https://example.com/s?k=G-Shock") is None


def test_parse_search_url_invalid_path():
    assert parse_search_url("https://www.amazon.co.jp/dp/B00X") is None


def test_parse_search_url_no_keyword():
    r = parse_search_url("https://www.amazon.co.jp/s?rh=n%3A337470011")
    assert r is not None
    assert r["keyword"] is None
    assert r["rh"] == "n:337470011"


# ----------------------------------------------------------------------------
# build_search_url_with_page
# ----------------------------------------------------------------------------
def test_build_search_url_with_page_first():
    assert build_search_url_with_page("https://www.amazon.co.jp/s?k=X", 1) \
        == "https://www.amazon.co.jp/s?k=X"


def test_build_search_url_with_page_append():
    r = build_search_url_with_page("https://www.amazon.co.jp/s?k=X", 3)
    assert "page=3" in r
    assert "k=X" in r


def test_build_search_url_with_page_override():
    r = build_search_url_with_page("https://www.amazon.co.jp/s?k=X&page=2", 5)
    assert "page=5" in r
    assert "page=2" not in r


# ----------------------------------------------------------------------------
# parse_asin_from_url
# ----------------------------------------------------------------------------
def test_parse_asin_dp():
    assert parse_asin_from_url("https://www.amazon.co.jp/dp/B08N5WRWNW") == "B08N5WRWNW"


def test_parse_asin_gp_product():
    assert parse_asin_from_url(
        "https://www.amazon.co.jp/gp/product/B0123456ZZ/ref=foo"
    ) == "B0123456ZZ"


def test_parse_asin_invalid():
    assert parse_asin_from_url("https://www.amazon.co.jp/somepage") is None
    assert parse_asin_from_url("") is None


def test_parse_asin_uppercased():
    assert parse_asin_from_url("https://www.amazon.co.jp/dp/b08n5wrwnw") == "B08N5WRWNW"


# ----------------------------------------------------------------------------
# build_amazon_tab_name
# ----------------------------------------------------------------------------
def test_build_amazon_tab_name_basic():
    assert build_amazon_tab_name("gshock") == "amazon_gshock"


def test_build_amazon_tab_name_sanitize():
    assert build_amazon_tab_name("G-Shock Mens") == "amazon_G_Shock_Mens"


def test_build_amazon_tab_name_empty():
    assert build_amazon_tab_name("") == "amazon_unknown"
    assert build_amazon_tab_name(None) == "amazon_unknown"


# ----------------------------------------------------------------------------
# dedupe_key (= sheet_writer_amazon)
# ----------------------------------------------------------------------------
def test_dedupe_key_amazon():
    assert dedupe_key("https://www.amazon.co.jp/dp/B08N5WRWNW") == "amzn:B08N5WRWNW"
    assert dedupe_key("https://www.amazon.co.jp/dp/B08N5WRWNW/ref=foo") == "amzn:B08N5WRWNW"


def test_dedupe_key_consistent_between_search_and_writer():
    """amazon_search.parse_asin_from_url と sheet_writer_amazon.dedupe_key が 同 ASIN を生む."""
    url = "https://www.amazon.co.jp/dp/B08N5WRWNW"
    asin = parse_asin_from_url(url)
    key = dedupe_key(url)
    assert key == f"amzn:{asin}"


# ----------------------------------------------------------------------------
# product_id_estimated from title (= G-shock model regex)
# ----------------------------------------------------------------------------
def test_gshock_model_regex_basic():
    assert _extract_product_id_estimated_from_title(
        "[カシオ] 腕時計 G-SHOCK GM-6900YRA-8JF メンズ"
    ) == "GM-6900YRA-8JF"


def test_gshock_model_regex_lowercase_input():
    assert _extract_product_id_estimated_from_title(
        "Casio g-shock DW-5600BB-1 black"
    ) == "DW-5600BB-1"


def test_gshock_model_regex_no_match():
    assert _extract_product_id_estimated_from_title("G-Shock メンズ ブラック") == ""
    assert _extract_product_id_estimated_from_title("") == ""


# ----------------------------------------------------------------------------
# is_gshock_item (= run_harvest_amazon_search brand filter)
# ----------------------------------------------------------------------------
def test_is_gshock_item_direct_brand():
    from run_harvest_amazon_search import is_gshock_item
    assert is_gshock_item("G-SHOCK", "DW-5600BB-1") is True
    assert is_gshock_item("G-Shock", "anything") is True
    assert is_gshock_item("ジーショック", "anything") is True


def test_is_gshock_item_casio_with_title_indicator():
    from run_harvest_amazon_search import is_gshock_item
    assert is_gshock_item("CASIO(カシオ)", "[カシオ] G-SHOCK DW-5600BB-1 メンズ") is True
    assert is_gshock_item("カシオ", "Gショック AW-591-2AJF") is True


def test_is_gshock_item_casio_without_indicator_rejected():
    """CASIO brand でも title に G-shock indicator なし → reject (= Baby-G / Edifice 除外)."""
    from run_harvest_amazon_search import is_gshock_item
    assert is_gshock_item("CASIO(カシオ)", "[カシオ] Baby-G BGD-565") is False
    assert is_gshock_item("CASIO", "EDIFICE EFR-552") is False
    assert is_gshock_item("CASIO", "PRO TREK PRW-50") is False


def test_is_gshock_item_other_brand_rejected():
    """CITIZEN 等 他ブランドは reject (= 5/11 5 件 sample 課題対応)."""
    from run_harvest_amazon_search import is_gshock_item
    assert is_gshock_item(
        "CITIZEN(シチズン)",
        "[CITIZEN] 腕時計 PROMASTER PMD56-2951 メンズ"
    ) is False
    assert is_gshock_item("SEIKO", "SEIKO 5 スポーツ") is False


def test_is_gshock_item_empty_brand_fallback():
    """brand 空 + title に G-shock indicator + 型番 regex → keep (fallback)."""
    from run_harvest_amazon_search import is_gshock_item
    assert is_gshock_item("", "G-Shock DW-5600BB-1 black") is True
    # title に indicator なし → reject
    assert is_gshock_item("", "DW-5600BB-1 black") is False
    # indicator あるが 型番 なし → reject
    assert is_gshock_item("", "G-Shock メンズ") is False


# --------------------------------------------------------------------------
# collect_search_asins: 空ページ(ブロック疑い)リトライ (2026-07-03 false-0 対策)
# --------------------------------------------------------------------------
def _asin_html(*asins):
    return "".join(
        f'<div data-component-type="s-search-result" data-asin="{a}"></div>'
        for a in asins
    )


def test_collect_retries_on_empty_page(monkeypatch):
    """page1 が一過性ブロックで空 → リトライで回復し、 0件abort しないこと."""
    import scrapers.amazon_search_http as H

    # 実ブロックは「非空 HTML だが検索結果0件」(= parse で []、 captcha 無し)。
    block = "<html><body>no results</body></html>"
    # page1: block,block,回復(2件) / page2: block×リトライ (=真の末尾)
    seq = [block, block, _asin_html("B000000001", "B000000002"),
           block, block, block, block]
    calls = {"n": 0}

    def fake_fetch(session, url):
        i = calls["n"]
        calls["n"] += 1
        return (seq[i] if i < len(seq) else ""), False

    monkeypatch.setattr(H, "fetch_search_page", fake_fetch)
    monkeypatch.setattr(H, "_sleep_jitter", lambda a, b: None)
    r = H.collect_search_asins(object(), "https://www.amazon.co.jp/s?k=x", max_pages=2)
    # リトライで page1 の 2 件を回収 (= false-0 abort しない)
    assert r["asins"] == ["B000000001", "B000000002"]


def test_collect_genuine_empty_breaks(monkeypatch):
    """リトライ後も空なら真の末尾として break (無限リトライしない)."""
    import scrapers.amazon_search_http as H
    monkeypatch.setattr(H, "fetch_search_page",
                        lambda s, u: ("<html>no results</html>", False))
    monkeypatch.setattr(H, "_sleep_jitter", lambda a, b: None)
    r = H.collect_search_asins(object(), "https://www.amazon.co.jp/s?k=x", max_pages=3)
    assert r["asins"] == []
