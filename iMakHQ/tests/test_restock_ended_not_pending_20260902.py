# -*- coding: utf-8 -*-
"""終了した出品を「入稿待ち」に混ぜない (2026-09-02)。

## 実害
RESTOCK の書戻しは数量だけ見ていたので、**終了した出品**も「まだ入稿していない(qty=0)」と
同じ「入稿待ち」に入っていた。実測 (2026-09-02): 入稿待ち5件のうち **3件は既に終了済**
(8/24 / 8/26 / 9/1 に期限切れ)。revise では戻せないので、何をしても数字が減らない。
確証日は 7/24 で、**40日間ずっと「⚠要対応」と出続けていた**。

グローバル規約「DLQ/要対応リストを"墓場"にしない」に反する状態だったので、
終了済を別に数え、要対応から外す。出し直すなら新規出品という別の判断になる。
"""
import os
import sys

_HQ_TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
if _HQ_TOOLS not in sys.path:
    sys.path.insert(0, _HQ_TOOLS)

import psa_restock_writeback as W  # noqa: E402


ITEMS = [{"itemID": "live_ok"}, {"itemID": "live_zero"},
         {"itemID": "ended"}, {"itemID": "unreadable"}]
QTY = {"live_ok": 1, "live_zero": 0, "ended": 0, "unreadable": None}


def test_ended_listing_is_not_counted_as_pending():
    cls = W.classify_restock(ITEMS, QTY,
                             {"live_zero": "Active", "ended": "Completed"})
    assert cls["done"] == ["live_ok"]
    assert cls["pending"] == ["live_zero"]        # 生きていて数量0 = 本当に入稿待ち
    assert cls["ended"] == ["ended"]              # 終了済は別枠
    assert cls["unknown"] == ["unreadable"]
    assert cls["status"]["ended"] == W.ST_ENDED


def test_without_status_map_behaviour_is_unchanged():
    """状態が取れなかった時は従来どおり (勝手に終了済にしない = fail-closed)。"""
    cls = W.classify_restock(ITEMS, QTY)
    assert cls["pending"] == ["live_zero", "ended"]
    assert cls["ended"] == []


def test_unknown_wins_over_ended():
    """数量が読めない時は状態が何であれ『不明』。済にも終了済にもしない。"""
    cls = W.classify_restock([{"itemID": "x"}], {"x": None}, {"x": "Completed"})
    assert cls["unknown"] == ["x"]
    assert cls["ended"] == []
