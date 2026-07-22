"""amazon 基本ポイント抽出 _extract_points_jpy の regression (2026-07-22).

Harvest `extract_points_jpy` (iMakHarvest commit 9b28c3d) の移植版。
安全方針: points ≈ price×pct% の内部整合チェック (± price1% + 20円) で基本分のみ採用、
campaign ポイント (Amazon Mastercard 等) は price×pct と一致しないため弾く。fail-closed。
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


def test_basic_points_accepted():
    """price×pct と整合する基本ポイントを採用 (14085×13%≈1831)."""
    assert _extract_points_jpy("1,831ポイント (13%)", 14085) == 1831


def test_campaign_points_filtered_out():
    """基本(整合) + campaign(不整合) 混在 → 整合する基本分のみ採用."""
    html = "1,831ポイント (13%) その後 2,165ポイント (14%)"
    assert _extract_points_jpy(html, 14085) == 1831


def test_inconsistent_only_returns_none():
    """price×pct と一致しない campaign 表記だけ → None (fail-closed、誤って campaign を拾わない)."""
    assert _extract_points_jpy("2,165ポイント (14%)", 14085) is None


def test_no_points_text_returns_none():
    """ポイント表記が無い → None (呼出側で「表示なし=K=0」に解釈)."""
    assert _extract_points_jpy("在庫あり。 残り1点", 14085) is None


def test_no_price_returns_none():
    """price 不明 → 検証不能 → None (fail-closed)."""
    assert _extract_points_jpy("1,831ポイント (13%)", None) is None
    assert _extract_points_jpy("1,831ポイント (13%)", 0) is None


def test_points_ge_price_rejected():
    """ポイントが価格以上 = 異常 → 採用しない."""
    assert _extract_points_jpy("20,000ポイント (13%)", 14085) is None


def test_empty_html_returns_none():
    assert _extract_points_jpy("", 14085) is None
