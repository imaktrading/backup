"""amazon_scraper stock-detection regression test.

2026-04-29 false-positive 12/12 バグ修正の固定化:
  - 旧ロジック: html 全体に「在庫切れ」/「現在お取り扱いできません」キーワード grep
                → hidden widget (related items / variation placeholder) で誤検出
  - 新ロジック: id="add-to-cart-button" 存在 → IN_STOCK
                id="outOfStock" 存在 → SOLD
                どちらも無し → 判定不能 (None, fail-closed)

検体は Takaaki さん目視確認: 12 件全て in_stock な anello グランデショルダーバッグ
バリエーション。debug/probe_amazon_cart.py で 3 ASIN を requests + selenium で取得。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Phase 7a: cycle precheck で実行する 検体ベース テスト群 (HTML サンプルのみ、network なし)
pytestmark = pytest.mark.offline

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SAMPLES_DIR = ROOT / "debug" / "amazon_samples"


# 検体: 全て Takaaki さん目視確認で「在庫あり」(IN_STOCK)
IN_STOCK_HTML_FILES = [
    "requests_anello_B0BNHJJSZ6.html",
    "requests_anello_B0BNHR7J1X.html",
    "requests_anello_B0D1C2146V.html",
    "selenium_anello_B0BNHJJSZ6.html",
    "selenium_anello_B0BNHR7J1X.html",
    "selenium_anello_B0D1C2146V.html",
]

# unqualifiedBuyBox 検体 (TEST_LOW row 116/120 で発見、おすすめ出品なし状態)
# Amazon 直販なし + 3rd party Featured Offer 不適格 → SOLD 扱い (購入経路なし)
NO_BUYBOX_SOLD_HTML_FILES = [
    "requests_no_buybox_B0CSP211SN.html",
    "requests_no_buybox_B0CSP2V9DP.html",
]


@pytest.fixture(scope="module")
def samples_available():
    # ★ 2026-06-21 no-skip 化 (HQ §): 検体不在を skip でなく FAIL にする。
    # offline gate (run_cycle precheck + pre-commit) は検体が無いと全 skip → exit 0 = 偽 pass で
    # 壊れた scraper 変更を silent に通す = HIGH/LOW 3日停止と同型の fail-OPEN。 検体不在は赤くする。
    samples = list(SAMPLES_DIR.glob("*.html")) if SAMPLES_DIR.exists() else []
    if not samples:
        pytest.fail(
            f"Amazon offline 検体が見つからない ({SAMPLES_DIR})。 offline gate が silent skip すると "
            f"検知ロジックの破壊を素通りさせるため、 検体不在は SKIP でなく FAIL 扱い。 検体を配置すること。"
        )
    return SAMPLES_DIR


@pytest.mark.parametrize("filename", IN_STOCK_HTML_FILES)
def test_offline_amazon_in_stock(samples_available, filename):
    """検体 6 件 (requests x3 + selenium x3): 全て IN_STOCK 判定."""
    from scrapers.amazon_scraper import _detect_stock  # noqa: PLC0415
    path = samples_available / filename
    if not path.exists():
        pytest.skip(f"sample missing: {path.name}")
    html = path.read_text(encoding="utf-8", errors="replace")
    verdict, reason = _detect_stock(html)
    assert verdict is True, (
        f"{filename}: detection returned ({verdict}, {reason}), expected True (in_stock)."
    )
    # 6/2 signal 拡張: cart_button / submit_buy_now / buy_now_text /
    # availability_in_stock いずれかで in_stock 判定
    assert reason in (
        "cart_button", "submit_buy_now", "buy_now_text",
    ) or reason.startswith("availability_in_stock"), (
        f"{filename}: unexpected reason {reason!r}"
    )


# 2026-06-02 偽陰性回帰防止: ユーザー目視「在庫なし」 だが #availability text に
# 「残り N 点」 が含まれる listing (= Marketplace 出品のみ、 Amazon 公式 から購入不可)。
# 旧 logic で「残り」 を在庫あり signal にしてたため in_stock 誤判定。
# fail-closed と整合させるため verdict が True でないこと (= False or None) のみ assert。
FALSENEG_SOLD_HTML_FILES = [
    "falseneg_B06XCDPKXG.html",
    "falseneg_B09TFB192X.html",
    "falseneg_B00RJJQE6Y.html",
]


@pytest.mark.parametrize("filename", FALSENEG_SOLD_HTML_FILES)
def test_offline_amazon_falseneg_sold_is_not_in_stock(samples_available, filename):
    """6/2 偽陰性 3 件: 「残り N 点」 表記の sold listing。 in_stock 判定しないことを担保."""
    from scrapers.amazon_scraper import _detect_stock  # noqa: PLC0415
    path = samples_available / filename
    if not path.exists():
        pytest.skip(f"sample missing: {path.name}")
    html = path.read_text(encoding="utf-8", errors="replace")
    verdict, reason = _detect_stock(html)
    # fail-closed: False (= 明確 sold) も None (= 判定不能、 D列空欄維持) も許容
    assert verdict is not True, (
        f"{filename}: detection returned ({verdict}, {reason}), "
        f"expected NOT True (sold or undetermined)."
    )


@pytest.mark.parametrize("filename", NO_BUYBOX_SOLD_HTML_FILES)
def test_offline_amazon_no_buybox_is_sold_via_unqualified(samples_available, filename):
    """unqualifiedBuyBox 検体: 一次判定 SOLD ('unqualifiedBuyBox' reason).
    実運用では Selenium fallback で再判定するが、_detect_stock 単体は False を返す。"""
    from scrapers.amazon_scraper import _detect_stock  # noqa: PLC0415
    path = samples_available / filename
    if not path.exists():
        pytest.skip(f"sample missing: {path.name}")
    html = path.read_text(encoding="utf-8", errors="replace")
    verdict, reason = _detect_stock(html)
    assert verdict is False
    assert reason == "unqualifiedBuyBox"


# 2026-06-02 HQ § Rule 0 検体: 販売元 identity gate.
# 「販売元 = Amazon.co.jp」 のみ in_stock=True。 第三者販売 (FBA 含む) は取下げ対象。
SELLER_GATE_SAMPLES = [
    # (filename, expected_in_stock, expected_reason_prefix, note)
    # 2026-07-22: primary-availability-message span 優先化で #availability の「在庫あり。」を
    # 先に拾うようになった (verdict=True は不変、 reason が submit_buy_now → availability_in_stock)。
    ("newincart_B0F9JP4JX5_row440.html",     True,  "availability_in_stock", "Amazon 直販 NEW"),
    ("usedonly_B07XGKZTRF_row549.html",      False, "third_party_seller",   "中古化 FBA 第三者"),
    ("usedonly_B0C6LMYHJT_row594.html",      None,  "no_signal",            "中古化 buy box 不在"),
    ("soldout_B018LSERHE_row554.html",       False, "unqualifiedBuyBox",    "真の売切"),
    ("soldout_B09MKCQKNV_row689.html",       False, "unqualifiedBuyBox",    "真の売切"),
]


@pytest.mark.parametrize("filename,expected,reason_prefix,note", SELLER_GATE_SAMPLES)
def test_offline_amazon_seller_identity_gate(samples_available, filename, expected, reason_prefix, note):
    """HQ 2026-06-02 § Rule 0: 販売元 = Amazon.co.jp のみ in_stock=True。

    第三者販売 (FBA 含む) は 中古化 / 価格不安定 / 出品消滅 の発生源 → 取下げ対象。
    """
    from scrapers.amazon_scraper import _detect_stock  # noqa: PLC0415
    path = samples_available / filename
    if not path.exists():
        pytest.skip(f"sample missing: {path.name}")
    html = path.read_text(encoding="utf-8", errors="replace")
    verdict, reason = _detect_stock(html)
    assert verdict is expected, (
        f"{filename} ({note}): got ({verdict!r}, {reason!r}), expected {expected!r}"
    )
    assert reason.startswith(reason_prefix), (
        f"{filename} ({note}): reason {reason!r} does not start with {reason_prefix!r}"
    )


# 2026-06-03 HQ § fail-closed bug fix 回帰テスト:
# 判定不能 (None) / 取れない (raw に in_stock 無し) → is_sold=True に倒さない (= skip)。

def test_fetch_product_inventory_returns_none_when_raw_in_stock_is_none():
    """raw に in_stock=None (= bot 検知 / 判定不能 page) → fetch_product_inventory が
    None 返却 (= 上流で is_sold=None で skip)。

    旧 logic: bool(raw.get("in_stock", False)) で default False=売切 に倒れる致命バグ。
    """
    from scrapers import amazon_scraper  # noqa: PLC0415
    # _fetch_via_requests を stub (= raw に in_stock 無い dict 返却 で 旧バグ再現条件)
    original = amazon_scraper._fetch_via_requests
    try:
        amazon_scraper._fetch_via_requests = lambda url: {"name": "x", "price_jpy": None}
        # use_selenium_fallback=False で Selenium path off (= requests のみで判定)
        result = amazon_scraper.fetch_product_inventory(
            "https://www.amazon.co.jp/dp/B0FAKE0001/",
            driver=None, use_selenium_fallback=False,
        )
        assert result is None, (
            f"raw に in_stock 無し → None 返却が正解 (= 上流 skip)、 got: {result!r}"
        )
    finally:
        amazon_scraper._fetch_via_requests = original


def test_fetch_product_inventory_returns_none_when_raw_in_stock_explicitly_none():
    """raw["in_stock"] = None (= 明示判定不能) → None 返却."""
    from scrapers import amazon_scraper  # noqa: PLC0415
    original = amazon_scraper._fetch_via_requests
    try:
        amazon_scraper._fetch_via_requests = lambda url: {
            "name": "x", "in_stock": None, "price_jpy": None,
        }
        result = amazon_scraper.fetch_product_inventory(
            "https://www.amazon.co.jp/dp/B0FAKE0002/",
            driver=None, use_selenium_fallback=False,
        )
        assert result is None, (
            f"raw['in_stock']=None → None 返却が正解、 got: {result!r}"
        )
    finally:
        amazon_scraper._fetch_via_requests = original


def test_fetch_product_inventory_preserves_explicit_true_false():
    """明示 True/False は dict 返却 (= 正常 path 維持)."""
    from scrapers import amazon_scraper  # noqa: PLC0415
    original = amazon_scraper._fetch_via_requests
    try:
        for in_stock_val in (True, False):
            amazon_scraper._fetch_via_requests = lambda url, v=in_stock_val: {
                "name": "x", "in_stock": v, "price_jpy": 100 if v else None,
            }
            result = amazon_scraper.fetch_product_inventory(
                "https://www.amazon.co.jp/dp/B0FAKE0003/",
                driver=None, use_selenium_fallback=False,
            )
            assert result is not None
            assert result["skus"][0]["in_stock"] is in_stock_val
    finally:
        amazon_scraper._fetch_via_requests = original


def test_amazon_constants_present():
    """新ロジックの判定軸定数が module に存在することを担保."""
    from scrapers.amazon_scraper import (
        CART_BUTTON_PATTERN, OUT_OF_STOCK_DIV_PATTERN, UNQUALIFIED_BUYBOX_PATTERN,
    )
    assert CART_BUTTON_PATTERN == 'id="add-to-cart-button"'
    assert OUT_OF_STOCK_DIV_PATTERN == 'id="outOfStock"'
    assert UNQUALIFIED_BUYBOX_PATTERN == 'id="unqualifiedBuyBox_feature_div"'


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
