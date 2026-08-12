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
      verdict: "IN_STOCK" / "SOLD" / "AUCTION" / "real_err"
    """
    # オークション化検知 (2026-06-10): 通常出品のみ仕入対象。 auction listing は
    # checkout-button-container 不在 + bid-button 存在 → 取下げ対象 (in_stock=False)。
    # 旧 logic では container 不在 = real_err に倒れ取下げされず fail-OPEN だった。
    if 'data-testid="bid-button"' in html:
        return "AUCTION", "bid-button (auction listing, 仕入不可→取下げ)"
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

    ★ 2026-06-21 no-skip 化 (HQ §): 検体不在は skip でなく FAIL。 mercari は HIGH 主力で、
    offline gate が検体不在 silent skip すると 検知ロジック破壊を素通りさせる (= fail-OPEN)。
    """
    samples = list(SAMPLES_DIR.glob("*.html")) if SAMPLES_DIR.exists() else []
    if not samples:
        pytest.fail(
            f"Mercari offline 検体が見つからない ({SAMPLES_DIR})。 検体不在の silent skip は "
            f"壊れた変更を通すため SKIP でなく FAIL。 検体を配置すること。"
        )
    return SAMPLES_DIR


@pytest.mark.offline
@pytest.mark.parametrize("item_id", IN_STOCK_ITEMS)
def test_offline_html_in_stock(samples_available, item_id):
    """検体 HTML 11 件: 在庫あり判定が IN_STOCK か."""
    path = samples_available / f"in_stock_{item_id}.html"
    if not path.exists():
        pytest.skip(f"sample missing: {path.name}")
    html = path.read_text(encoding="utf-8", errors="replace")
    verdict, reason = _detect_from_html(html)
    assert verdict == "IN_STOCK", f"{item_id}: got {verdict} ({reason})"


@pytest.mark.offline
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
# オークション化検知 (2026-06-10 制定): 通常出品 → auction 変更は取下げ対象
# ============================================================================
@pytest.mark.offline
def test_offline_auction_is_takedown():
    """auction listing (bid-button 存在 / container 不在) → AUCTION 判定."""
    html = (
        '<div><h1>商品名</h1>'
        '<button data-testid="bid-button">入札する</button>'
        '<div data-testid="price">¥12,000</div></div>'
    )
    verdict, reason = _detect_from_html(html)
    assert verdict == "AUCTION", f"got {verdict} ({reason})"


@pytest.mark.offline
def test_offline_normal_not_misdetected_as_auction():
    """通常出品 (checkout-button-container + purchase) は IN_STOCK のまま誤検知しない."""
    html = (
        '<div data-testid="checkout-button-container">'
        '<div data-testid="checkout-button" name="purchase">購入手続きへ</div></div>'
    )
    verdict, reason = _detect_from_html(html)
    assert verdict == "IN_STOCK", f"got {verdict} ({reason})"


@pytest.mark.offline
def test_offline_auction_without_bid_button_still_not_purchasable():
    """auction 終了/入札不可でも checkout container 不在なら購入不可扱い (fail-OPEN 防止).

    ★ 2026-08-12: bid-button の有無だけに依存すると、auction の状態遷移 (受付前/終了後) で
      判定が IN_STOCK に戻り得る。購入導線が無いものを在庫ありと言わないことを固定する。
    """
    html = ('<div><h1>商品名</h1><div>オークションは終了しました</div>'
            '<div data-testid="price">¥12,000</div></div>')
    verdict, reason = _detect_from_html(html)
    assert verdict != "IN_STOCK", f"got {verdict} ({reason})"


@pytest.mark.offline
def test_offline_bid_word_in_description_not_misdetected():
    """説明文に「入札」の語があるだけの通常出品を AUCTION 誤判定しない (取下げ暴発防止)."""
    html = ('<div data-testid="checkout-button-container">'
            '<div data-testid="checkout-button" name="purchase">購入手続きへ</div></div>'
            '<div id="item-info">他サイトの入札履歴あり。ノークレームノーリターン</div>')
    verdict, reason = _detect_from_html(html)
    assert verdict == "IN_STOCK", f"got {verdict} ({reason})"


# Live: Takaaki さん目視確認の auction 化検体 (2026-06-10、 LOW/HIGH r468/r470)。
# ★ 2026-08-12: 両 URL とも出品自体が削除され status=DELETED になった (auction 終了 → 削除)。
#   「今も AUCTION であること」を live に期待するのは検体の寿命に賭ける設計で、必ず腐って
#   落ちっぱなしになる (= 誰も見なくなる)。よって live 側は **恒久に成り立つ性質だけ** を見る:
#   「一度 購入不可 (auction/売切/削除) になった listing が再び購入可に戻らない」= fail-OPEN 防止。
#   AUCTION の DOM 判定そのものは上の offline test で固定する (ネット非依存で腐らない)。
KNOWN_NOT_PURCHASABLE_URLS = [
    ("r468", "https://jp.mercari.com/item/m18442750029"),
    ("r470", "https://jp.mercari.com/item/m69534401329"),
]
TERMINAL_STATUSES = {"AUCTION", "DELETED", "SOLD_OUT"}


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


@pytest.mark.live
@pytest.mark.parametrize("label,url", KNOWN_NOT_PURCHASABLE_URLS)
def test_live_not_purchasable_stays_takedown(label, url):
    """Live: 購入不可になった listing が in_stock=False のままか (= 取下げ対象、fail-OPEN 防止).

    元は auction 化検体。現在は削除済だが「購入不可 → 二度と在庫ありに戻らない」性質は不変
    なので、検体が腐っても意味を持ち続ける形にしてある (2026-08-12)。
    """
    from scrapers.mercari_scraper import fetch_product_inventory  # noqa: PLC0415
    info = fetch_product_inventory(url, use_selenium_fallback=True)
    assert info is not None, f"{label}: scraper returned None (未検知 = fail-OPEN)"
    assert info["skus"][0]["in_stock"] is False, (
        f"{label}: 購入不可のはずが in_stock=True (取下げされない = fail-OPEN)"
    )
    assert info["status"] in TERMINAL_STATUSES, f"{label}: got status={info['status']}"


# ============================================================================
# CLI (旧 script 互換)
# ============================================================================
if __name__ == "__main__":
    # pytest に委譲
    sys.exit(pytest.main([__file__, "-v"]))
