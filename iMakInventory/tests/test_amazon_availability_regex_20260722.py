"""amazon scraper availability 抽出の regex 誤マッチ regression (2026-07-22).

真因: 旧 _detect_stock は `<div[^>]*id="availability"[^>]*>(.*?)</div>` で availability text を
抽出していたが、 先頭 [^>]* が **手前の CSS/wrapper 内の id="availability" 部分文字列**
(例 data-csa-c-content-id="availability" や .availabilityMoreDetailsIcon style block) に誤マッチし、
非貪欲 (.*?) が CSS だけ拾って本物の「残りN点」div に届かず no_signal → fail-closed。
実害: row686 B09C64HBQX (カシオ GBD-200-1ER) が「残り1点」= 在庫ありなのに連続13回 None で
persistent error 化 (item_id 空 = eBay 未出品なので fail-OPEN ではないが、 D列 stale で出品機会損失)。

修正: Amazon の意味的クラス primary-availability-message span を優先ソースにする。
検体6/6 (旧 row115/118/506/524/535 + 新 row686) で正しい在庫テキスト取得を確認済。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from scrapers.amazon_scraper import _detect_stock  # noqa: E402

# row686 検体を最小再現した DOM 断片:
# 1. 手前に data-csa-c-content-id="availability" を持つ wrapper + CSS (旧 regex の誤マッチ源)
# 2. その後に本物の primary-availability-message span (残り1点 = 在庫あり)
_CSS_DECOY_THEN_REAL = (
    '<div class="wrap" data-csa-c-content-id="availability">'
    '<style>.availabilityMoreDetailsIcon { width: 12px; vertical-align: baseline; }</style>'
    '</div>'
    '<div id="availability" class="a-section a-spacing-base a-spacing-top-micro }">'
    '<span class="a-size-base a-color-price primary-availability-message a-text-bold">'
    ' 残り1点 ご注文はお早めに </span>'
    '<span class="availabilityHelpLink"><a href="#">在庫状況</a>について</span>'
    '</div>'
    'Amazon.co.jp が発送'
)


def test_css_decoy_does_not_swallow_real_availability():
    """手前の CSS/wrapper 誤マッチに引きずられず、 本物の「残り1点」を拾って在庫あり判定する。
    (旧実装はここで no_signal → None を返し fail-closed 永久滞留していた)。"""
    verdict, reason = _detect_stock(_CSS_DECOY_THEN_REAL, rendered=True)
    assert verdict is True, f"expected in-stock, got {verdict} ({reason})"


def test_primary_availability_message_soldout_still_detected():
    """primary-availability-message span 経由でも在庫切れは False で拾う (取下げ側の安全)。"""
    html = (
        '<div id="availability" class="a-section">'
        '<span class="a-color-price primary-availability-message">現在在庫切れです。</span>'
        '</div>Amazon.co.jp が発送'
    )
    assert _detect_stock(html, rendered=True)[0] is False


def test_third_party_gate_still_wins_over_availability_span():
    """primary-availability-message が在庫あり表示でも、 出品者配送 (第三者) は取下げ対象 (Rule 0)。"""
    html = (
        '<div id="availability" class="a-section">'
        '<span class="primary-availability-message">残り1点 ご注文はお早めに</span>'
        '</div>この商品は、出品者によって配送されます。'
    )
    assert _detect_stock(html, rendered=True)[0] is False


# --- 検体駆動 (specimen が存在する環境でのみ実行。 untracked のため CI では skip) ---

_SPECIMEN = ROOT / "debug" / "amazon_specimens" / "row686_B09C64HBQX.html"


@pytest.mark.skipif(not _SPECIMEN.exists(), reason="specimen not present (untracked)")
def test_row686_specimen_is_in_stock():
    html = _SPECIMEN.read_text(encoding="utf-8", errors="replace")
    verdict, reason = _detect_stock(html, rendered=True)
    assert verdict is True, f"row686 should be in-stock (残り1点), got {verdict} ({reason})"
