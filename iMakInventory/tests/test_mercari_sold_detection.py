"""mercari_scraper sold-detection regression test.

2026-04-29 HTML 検体 21 件分析 (in_stock 11 / sold 10) で確定した判定軸:
  1) [data-testid="checkout-button-container"] が描画 (universal hydration proxy)
  2) container 内の checkout-button 不在 → SOLD (取引中派生)
  3) checkout-button div に disabled__ class or name="disabled" → SOLD
  4) checkout-button div に name="purchase" → IN_STOCK
  5) 新パターン → real_err (fail-closed)

本テストは 2 種類:
  - test_offline_html_*: 保存済 HTML 検体を regex 解析し判定軸の安定性を検証
                        (pre-commit / CI で常時実行、ネット不要)
  - test_live_known_sold_urls: Live Mercari URL を叩いて Selenium ロジックの動作確認
                              (pytest -m live で明示的に実行、環境依存)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

# parent path 確保 (iMakInventory ルート)
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SAMPLES_DIR = ROOT / "debug" / "html_samples"


# ============================================================================
# HTML 文字列ベースの判定 (offline pytest 用)
# ============================================================================
def _detect_from_html(html: str) -> tuple[str, str]:
    """HTML 文字列から在庫状態を判定. Selenium ロジックと同じ判定軸。

    Returns: (verdict, reason)
      verdict: "IN_STOCK" / "SOLD" / "real_err"
    """
    if 'data-testid="checkout-button-container"' not in html:
        return "real_err", "checkout-button-container not found"

    m = re.search(r'<div\b([^>]*?)data-testid="checkout-button"([^>]*)>', html)
    if not m:
        return "SOLD", "checkout-button absent (transaction-in-progress 等)"

    div_tag = m.group(0).lower()
    if "disabled__" in div_tag:
        return "SOLD", 'disabled__ class'
    if 'name="disabled"' in div_tag:
        return "SOLD", 'name="disabled"'
    if 'name="purchase"' in div_tag:
        return "IN_STOCK", 'name="purchase"'
    return "real_err", "unknown checkout-button state"


# ============================================================================
# 検体定義
# ============================================================================
# 在庫あり 11 件 (HTML 検体収集済)
IN_STOCK_ITEMS = [
    "m13033508222", "m49383173561", "m82262228708", "m64819241726",
    "m85731918507", "m64454009245", "m34502758783", "m41555692668",
    "m27139398286", "m76741283035", "m12964510802",
]
# 在庫なし 10 件 (HTML 検体収集済)
SOLD_ITEMS = [
    "m96600846115", "m63571237049", "m63905828803", "m32993695536",
    "m69015839424", "m59588662304", "m94867178401", "m42421532190",
    "m95836277025", "m99325579898",
]

# Takaaki さん目視確認の Live URL (regression、live marker)
KNOWN_SOLD_URLS = [
    ("row6",   "https://jp.mercari.com/item/m81334162487"),
    ("row85",  "https://jp.mercari.com/item/m89212781202"),
    ("row87",  "https://jp.mercari.com/item/m86631907186"),
    ("row88",  "https://jp.mercari.com/item/m36837780005"),
    ("row118", "https://jp.mercari.com/item/m14968932238"),
    ("row127", "https://jp.mercari.com/item/m84213071035"),
    ("row128", "https://jp.mercari.com/item/m34247662912"),
    ("row129", "https://jp.mercari.com/item/m83933181328"),
    ("row131", "https://jp.mercari.com/item/m61680512158"),
]


# ============================================================================
# Offline tests (pytest, no network)
# ============================================================================
@pytest.fixture(scope="module")
def samples_available():
    """検体 HTML が存在するか確認 (debug/html_samples/)。
    存在しない環境では skip して、Live test 環境差を吸収する。
    """
    if not SAMPLES_DIR.exists():
        pytest.skip(f"HTML samples not found at {SAMPLES_DIR}")
    return SAMPLES_DIR


@pytest.mark.parametrize("item_id", IN_STOCK_ITEMS)
def test_offline_html_in_stock(samples_available, item_id):
    """検体 HTML 11 件: 在庫あり判定が IN_STOCK か."""
    path = samples_available / f"in_stock_{item_id}.html"
    if not path.exists():
        pytest.skip(f"sample missing: {path.name}")
    html = path.read_text(encoding="utf-8", errors="replace")
    verdict, reason = _detect_from_html(html)
    assert verdict == "IN_STOCK", f"{item_id}: got {verdict} ({reason})"


@pytest.mark.parametrize("item_id", SOLD_ITEMS)
def test_offline_html_sold(samples_available, item_id):
    """検体 HTML 10 件: 売切判定が SOLD か."""
    path = samples_available / f"sold_{item_id}.html"
    if not path.exists():
        pytest.skip(f"sample missing: {path.name}")
    html = path.read_text(encoding="utf-8", errors="replace")
    verdict, reason = _detect_from_html(html)
    assert verdict == "SOLD", f"{item_id}: got {verdict} ({reason})"


# ============================================================================
# Live tests (pytest -m live、ネット必須、時間がかかる)
# ============================================================================
@pytest.mark.live
@pytest.mark.parametrize("label,url", KNOWN_SOLD_URLS)
def test_live_known_sold_urls(label, url):
    """Live Mercari URL: Takaaki さん目視確認の 9 件で SOLD 検出か."""
    from scrapers.mercari_scraper import fetch_product_inventory  # noqa: PLC0415
    info = fetch_product_inventory(url, use_selenium_fallback=True)
    assert info is not None, f"{label}: scraper returned None"
    assert info["skus"][0]["in_stock"] is False, (
        f"{label}: false negative (scraper says in_stock=True for known-sold URL)"
    )


# ============================================================================
# CLI (旧 script 互換)
# ============================================================================
if __name__ == "__main__":
    # pytest に委譲
    sys.exit(pytest.main([__file__, "-v"]))
