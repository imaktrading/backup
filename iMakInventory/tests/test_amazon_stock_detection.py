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
    if not SAMPLES_DIR.exists():
        pytest.skip(f"Amazon samples not found at {SAMPLES_DIR}")
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
    assert reason == "cart_button"


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
