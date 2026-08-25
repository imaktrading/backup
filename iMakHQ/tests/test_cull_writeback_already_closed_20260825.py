# -*- coding: utf-8 -*-
"""自然終了した出品の後始末が落ちていた (2026-08-25)。

## 何が起きていたか
356901060098 (CASIO G-SHOCK RANGEMAN GW-9400J-1JF) は 2026-08-15 に **自然終了**していた。
8/23 の取下げでは eBay が `1047 Error - The auction has already been closed.` を返し、
`cull_writeback` は `Status == "Success"` の行しか後始末しないので **B列に死んだ itemID が
残った**。このシステムは B列が埋まっている = 出品中 として動くため、仕入元が戻っても
その商品は二度と出品されない (= 気づかれない取りこぼし)。

取下げ側 (`cull_end`) は 8/24 に「自然終了も済みリストに入れる」で同じ穴を塞いだが、
スプシの後始末側だけ残っていた。

## 直し方
**「既に閉じている」は成功と同じ扱い**にする。目的 (出品が生きていない) は達成されている。
"""
import os
import sys

_TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import cull_writeback as W  # noqa: E402


def _row(status, code="", msg="", iid="356901060098"):
    return {"Status": status, "ErrorCode": code, "ErrorMessage": msg, "ItemID": iid}


def test_success_is_ended():
    assert W.is_ended_row(_row("Success"))


def test_already_closed_is_ended():
    """実際に踏んだ行 (8/23 の結果CSV 30行目)。"""
    assert W.is_ended_row(
        _row("Failure", "1047", "Error - The auction has already been closed.|"))


def test_already_closed_detected_by_message_only():
    """コードが取れなくても文面で拾う。"""
    assert W.is_ended_row(_row("Failure", "", "The auction has already been closed."))


def test_other_failure_is_not_ended():
    """本当に失敗した行は後始末しない (まだ生きている出品の B列を消さない)。"""
    assert not W.is_ended_row(_row("Failure", "21916884", "Invalid item ID."))
    assert not W.is_ended_row(_row("Failure", "931", "Auth token is invalid."))


def test_row_without_itemid_is_ignored():
    assert not W.is_ended_row(_row("Success", iid=""))
