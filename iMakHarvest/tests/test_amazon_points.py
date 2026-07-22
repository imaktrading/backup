"""extract_points_jpy - Amazon 基本ポイント抽出 (= 実質仕入値 N=F−K 用) offline tests.

HQ 依頼 2026-07-22。 安全方針 = 「確実に付く分だけ」:
基本ポイントは points ≈ price×pct% で内部整合する。 campaign (カード) 分は一致しない。
"""
from __future__ import annotations

import pytest

from scrapers.amazon_search_http import extract_points_jpy, extract_price_jpy

pytestmark = pytest.mark.offline


def _html(price="14,080", body=""):
    return f'<div class="a-price-whole">{price}</div>{body}'


class TestExtractPriceJpy:
    def test_basic(self):
        assert extract_price_jpy(_html("14,080")) == 14080

    def test_missing(self):
        assert extract_price_jpy("<html>no price</html>") is None
        assert extract_price_jpy("") is None


class TestExtractPointsJpy:
    def test_base_points_consistent(self):
        # 実ページ B07VCHDWVR 相当: 14,080円 1,831pt(13%) → 14080*0.13=1830.4 ≈ 1831 ✓
        h = _html("14,080", "獲得予定 1,831ポイント (13%)")
        assert extract_points_jpy(h) == 1831

    def test_campaign_points_rejected(self):
        # campaign 分 (2,165pt(14%)) は price×pct と不整合 → 弾く。 基本分のみ採用
        h = _html("14,080",
                  "獲得予定 1,831ポイント (13%) ... Mastercardなら 2,165ポイント (14%)")
        assert extract_points_jpy(h) == 1831

    def test_campaign_only_returns_none(self):
        # 整合する基本分が無い (campaign のみ) → fail-closed None
        h = _html("14,080", "Mastercardなら 2,165ポイント (14%)")
        assert extract_points_jpy(h) is None

    def test_no_points_returns_none(self):
        assert extract_points_jpy(_html("14,080", "ポイント表記なし")) is None

    def test_no_price_returns_none(self):
        # price 不明 → 検証不能 → fail-closed
        assert extract_points_jpy("1,831ポイント (13%)") is None

    def test_points_exceed_price_rejected(self):
        h = _html("1,000", "20,000ポイント (10%)")
        assert extract_points_jpy(h) is None

    def test_rounding_tolerance(self):
        # 実ページ B0CP24Y77K 相当: 11,440円 1,378pt(12%) (= 1372.8 と誤差5 → 許容)
        h = _html("11,440", "1,378ポイント (12%)")
        assert extract_points_jpy(h) == 1378

    def test_price_passed_explicitly(self):
        assert extract_points_jpy("1,584ポイント (10%)", price_jpy=15840) == 1584

    def test_empty(self):
        assert extract_points_jpy("") is None


class TestPlanRow:
    """backfill tool の行計画 (formula_switch 2026-07-22 後: **K のみ書く**).

    N はシート関数 =(MあればM、なければF)−K (= HQ 設置) のため書かない。
    N セル書込は関数を壊す → plan は K 以外を含まないことが回帰条件。
    """

    def _plan(self, *a, **k):
        from tools.backfill_amazon_points_low import plan_row
        return plan_row(*a, **k)

    def test_points_only_k(self):
        p = self._plan(14080, 14080, 1831)
        assert p == {"k": 1831}

    def test_no_points_k_empty(self):
        p = self._plan(14080, 14080, None)
        assert p == {"k": ""}

    def test_fetch_fail_skips(self):
        assert self._plan(14080, None, None) is None

    def test_never_writes_n_or_f(self):
        # 価格乖離があっても K のみ (= N/F は書かない。 鮮度は監視くん M 担当)
        for sheet_f, page, pts in ((10000, 12000, 1200), (10000, 8000, 800), (None, 9000, 900)):
            p = self._plan(sheet_f, page, pts)
            assert set(p.keys()) == {"k"}
            assert p["k"] == pts
