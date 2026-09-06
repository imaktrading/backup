# -*- coding: utf-8 -*-
"""取下げの件数に、出品中の実状態を反映する (2026-09-06 ユーザー指摘「件数が変わらない」).

## なぜ
ボタンは「残り8件 — 今回8件 落とします / 出品枠が $1,454 空きます」と出していたのに、
押したら **0件**だった。8件とも補充されて在庫が戻っていたため、落とす直前の実機確認で
全部 除外された (これ自体は正しい fail-closed)。

原因は数える側が funnel CSV しか見ていないこと。funnel は静的なので、
**その後 補充された分がいつまでも候補に残る**。押しても減らないので残りが動かない。

数える側でも同じものを見る。ただし **eBay は叩かない** — 既にある live 一覧
(itemid_writeback_audit のキャッシュ) を読むだけ。表示のために API 枠を使わない方針
(2026-08-24 に表示目的の取得で取下げが5時間止まった) は変えない。
"""
from __future__ import annotations

import io
import os
import sys

import pytest

_HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_HQ, "tools"))
_PANEL = io.open(os.path.join(_HQ, "control_panel.py"), encoding="utf-8").read()
_CULL = io.open(os.path.join(_HQ, "tools", "cull_end.py"), encoding="utf-8").read()


@pytest.fixture(scope="module")
def C():
    import cull_end
    return cull_end


LIVE = {"111": {"avail": 0}, "222": {"avail": 1}, "333": {"avail": "0"}}


class TestStillOos:
    def test_quantity_zero_and_alive_is_a_candidate(self, C):
        assert C.still_oos({"item_id": "111"}, LIVE) is True

    def test_restocked_is_not_a_candidate(self, C):
        """★これが本丸。在庫が戻ったものを落としてはいけない。"""
        assert C.still_oos({"item_id": "222"}, LIVE) is False

    def test_missing_from_live_means_already_ended(self, C):
        assert C.still_oos({"item_id": "999"}, LIVE) is False

    def test_no_live_data_means_do_not_claim_it_is_a_candidate(self, C):
        """live が読めない時に「落とせる」と言い切らない (fail-closed)。"""
        assert C.still_oos({"item_id": "111"}, None) is False
        assert C.still_oos({"item_id": "111"}, {}) is False

    def test_string_quantity_is_handled(self, C):
        assert C.still_oos({"item_id": "333"}, LIVE) is True

    def test_broken_entry_does_not_crash(self, C):
        assert C.still_oos({"item_id": "111"}, {"111": "こわれた"}) is False
        assert C.still_oos({}, LIVE) is False


class TestCountWorkload:
    def test_it_reports_how_many_were_restocked(self):
        """減らせなかった理由を数字で出す (黙って0にしない)。"""
        i = _CULL.index("def count_workload(")
        body = _CULL[i:_CULL.index("\ndef ", i + 10)]
        assert 'out["restocked"] = n_before - len(eligible)' in body
        assert "picked = eligible[:CAP]" in body

    def test_it_never_calls_ebay(self):
        """表示のために API 枠を使わない (2026-08-24 の実害)。"""
        i = _CULL.index("def live_snapshot(")
        body = _CULL[i:_CULL.index("\ndef ", i + 10)]
        assert "CACHE" in body and "requests" not in body

    def test_stale_cache_is_said_so(self):
        i = _CULL.index("def live_snapshot(")
        body = _CULL[i:_CULL.index("\ndef ", i + 10)]
        assert "CACHE_MAX_AGE_SEC" in body and "時間前" in body


class TestPanelShowsWhy:
    def test_the_hint_says_why_it_cannot_be_pressed(self):
        assert 'ce.get("restocked")' in _PANEL
        assert "在庫が戻って落とせない" in _PANEL

    def test_it_says_what_to_do_next(self):
        """理由だけ出して終わらない。候補から消す手順まで書く。"""
        i = _PANEL.index("在庫が戻って落とせない")
        assert "ファネル分析" in _PANEL[i:i + 200]
