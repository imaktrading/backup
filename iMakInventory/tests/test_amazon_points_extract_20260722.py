"""amazon 獲得ポイント抽出 _extract_points_jpy の regression (2026-07-22 / defect修正 3a58a60 同期).

Harvest `extract_points_jpy` (iMakHarvest commit 3a58a60) の移植版。
真因: buybox の実表記は「ポイント: 1,831pt (13%)」(pt表記+タグ/&nbsp;分断)。旧 regex(「N,NNNポイント(X%)」
前提・全ページ走査)は buybox に不マッチし、カルーセル/よく一緒に購入の別商品 pt を拾っていた
(136件が別商品小額pt / 48件が campaign 24% を ±1% で誤通過)。
修正: `data-feature-name="pointsInsideBuyBox"/"points"` widget 内のみ抽出、widget無し→None、
整合チェック ±max(price×0.5%, 10円)。高率pt(>13.5%)も cap せず忠実採用(案A・ユーザー裁定)。
呼出側 (monitor_listings) が「fetch 成功 × in_stock × price 有効 なのに None」= 表示なし → K=0、
「fetch 失敗」= K 不触、と区別する。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scrapers.amazon_scraper import _extract_points_jpy  # noqa: E402

_WIDGET_BUYBOX = ('<div data-feature-name="pointsInsideBuyBox" data-csa-c-asin="B0X">'
                  '<span>ポイント: {pt}pt ({pct}%)</span></div>')
_WIDGET_INFO = '<div data-feature-name="points">ポイント: {pt}pt ({pct}%)</div>'


def test_buybox_widget_points_accepted():
    """buybox widget 内の整合ポイントを採用 (14085×13%≈1831)."""
    html = _WIDGET_BUYBOX.format(pt="1,831", pct=13)
    assert _extract_points_jpy(html, 14085) == 1831


def test_info_widget_points_accepted():
    """商品情報欄 widget (data-feature-name=points) からも抽出できる."""
    html = _WIDGET_INFO.format(pt="200", pct=20)
    assert _extract_points_jpy(html, 1000) == 200


def test_carousel_points_ignored_no_widget():
    """★ defect 再発防止: widget 外 (カルーセル/よく一緒に購入) の別商品 pt は拾わない → None."""
    html = ('<div>よく一緒に購入されている商品<span>33ポイント (24%)</span></div>'
            '<div class="carousel">128ポイント (2%)</div>')
    assert _extract_points_jpy(html, 14085) is None


def test_high_rate_points_faithfully_adopted():
    """★ 高率ポイント(>13.5%)も cap/フィルタせず忠実採用 (案A・ユーザー裁定 2026-07-22).
    price 1000 × 20% = 200pt が整合 → 200 を返す (キャンペーン終了は巡回の K↓ で自動追随)."""
    html = _WIDGET_INFO.format(pt="200", pct=20)
    assert _extract_points_jpy(html, 1000) == 200


def test_widget_present_but_inconsistent_returns_none():
    """widget はあるが price×pct と大きく不整合 (parse 事故/変則 layout) → None (値引きを盛らない)."""
    html = _WIDGET_INFO.format(pt="5,000", pct=13)  # 14085×13%=1831 と乖離
    assert _extract_points_jpy(html, 14085) is None


def test_tag_and_nbsp_split_tolerated():
    """widget 内が tag / &nbsp; で分断されていても除去・正規化して抽出できる."""
    html = ('<div data-feature-name="pointsInsideBuyBox">'
            '<span>ポイント:</span>&nbsp;<b>1,831</b>pt&nbsp;<span>(13%)</span></div>')
    assert _extract_points_jpy(html, 14085) == 1831


def test_no_widget_returns_none():
    """points widget が無い = ポイントなし → None (呼出側で「表示なし=K=0」に解釈)."""
    assert _extract_points_jpy("<div>在庫あり。 残り1点</div>", 14085) is None


def test_no_price_returns_none():
    """price 不明 → 検証不能 → None (fail-closed)."""
    html = _WIDGET_INFO.format(pt="1,831", pct=13)
    assert _extract_points_jpy(html, None) is None
    assert _extract_points_jpy(html, 0) is None


def test_points_ge_price_rejected():
    """ポイントが価格以上 = 異常 → None."""
    html = _WIDGET_INFO.format(pt="20,000", pct=13)
    assert _extract_points_jpy(html, 14085) is None


def test_empty_html_returns_none():
    assert _extract_points_jpy("", 14085) is None
