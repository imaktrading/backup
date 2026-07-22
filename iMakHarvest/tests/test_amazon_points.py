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
    """widget anchor 版 (2026-07-22 defect 修正後).

    defect: 全ページ走査が カルーセル/よく一緒に購入 の別商品ptを拾った
    (48件が24%等 / 136件が別商品の小額pt)。 → points widget 内のみ抽出。
    """

    @staticmethod
    def _widget(pts="1,831", pct=13, name="pointsInsideBuyBox"):
        return (f'<div data-feature-name="{name}" data-csa-c-type="widget">'
                f'<td> ポイント: </td><td><span>{pts}pt</span>&nbsp;'
                f'<span>({pct}%)</span></td></div>')

    def test_widget_basic(self):
        h = _html("14,080", self._widget("1,831", 13))
        assert extract_points_jpy(h) == 1831

    def test_points_feature_widget_also_works(self):
        h = _html("14,300", self._widget("143", 1, name="points"))
        assert extract_points_jpy(h) == 143

    def test_carousel_text_outside_widget_ignored(self):
        # ★ defect 回帰: widget 外の「Nポイント(X%)」(カルーセル/よく一緒に) は拾わない
        h = _html("14,300", "関連商品 33ポイント(1%) ... 6,435ポイント(24%)")
        assert extract_points_jpy(h) is None

    def test_no_widget_returns_none(self):
        assert extract_points_jpy(_html("14,080", "ポイント表記なし")) is None

    def test_widget_inconsistent_value_rejected(self):
        # widget があっても price×pct と不整合 (= parse 事故) → fail-closed
        h = _html("14,080", self._widget("9,999", 13))
        assert extract_points_jpy(h) is None

    def test_widget_points_exceed_price_rejected(self):
        h = _html("1,000", self._widget("2,000", 10))
        assert extract_points_jpy(h) is None

    def test_no_price_returns_none(self):
        assert extract_points_jpy(self._widget("1,831", 13)) is None

    def test_price_passed_explicitly(self):
        assert extract_points_jpy(self._widget("1,584", 10), price_jpy=15840) == 1584

    def test_high_campaign_pct_in_widget_is_kept(self):
        # widget 自身が 24% を表示するケース (= 実在のポイントアップ) は忠実に返す
        # (>13.5% の採否ポリシーは HQ 裁定 = sample 目視で判断)
        h = _html("26,730", self._widget("6,435", 24))
        assert extract_points_jpy(h) == 6435

    def test_empty(self):
        assert extract_points_jpy("") is None


class TestPlanRow:
    """backfill tool の行計画 (defect 修正後: **F=現在ページ価格 + K** を書く、 N は書かない).

    N はシート関数 =(MあればM、なければF)−K (= HQ 設置) のため書かない。
    F を現在価格へ同時更新することで 旧F × 現pt の混成 (= N 過小/過大) を防ぐ。
    """

    def _plan(self, *a, **k):
        from tools.backfill_amazon_points_low import plan_row
        return plan_row(*a, **k)

    def test_points_writes_f_and_k(self):
        assert self._plan(14080, 14080, 1831) == {"f": 14080, "k": 1831}

    def test_no_points_k_empty(self):
        assert self._plan(14080, 14080, None) == {"f": 14080, "k": ""}

    def test_fetch_fail_skips(self):
        assert self._plan(14080, None, None) is None

    def test_price_drift_updates_f_together(self):
        # 価格乖離時も F を現在価格へ揃える (= 混成防止、 defect 依頼 指示3)
        for sheet_f, page, pts in ((10000, 12000, 1200), (10000, 8000, 800), (None, 9000, 900)):
            p = self._plan(sheet_f, page, pts)
            assert p == {"f": page, "k": pts}
            assert "n" not in p  # N は絶対書かない (ARRAYFORMULA 保護)
