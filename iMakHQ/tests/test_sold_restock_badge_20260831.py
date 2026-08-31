# -*- coding: utf-8 -*-
"""売れた分を補充ボタンに残数ヒント + 青色を付ける (2026-08-31)。

> その対応するボタン、ヒントテキストに件数とか青くするとかしてくれない？放置しちゃう

cull_end / shelf_evict と同じ badge の仕組みに乗せる。sold_restock.count_workload は
eBay の per-item 状態確認 (ebay_status) をしない — live キャッシュがあれば使い、
無ければ unknown として数える (actionable と言い切らない。cull_end と同じ理由で
表示のために API 枠を使わない)。
"""
import inspect
import json
import os
import sys

_TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import sold_restock as SR  # noqa: E402

_PANEL = os.path.join(os.path.dirname(_TOOLS), "control_panel.py")
_SRC = open(_PANEL, encoding="utf-8").read()


def test_missing_report_is_reported_not_hidden(monkeypatch):
    monkeypatch.setattr(SR.W, "_find_desk_report", lambda: "")
    got = SR.count_workload()
    assert got["report"] is False
    assert got["error"]


def test_never_calls_per_item_ebay_status():
    """★表示のために API 枠を使わない (cull_end/shelf_evict と同じ理由)。"""
    src = inspect.getsource(SR.count_workload)
    for banned in ("ebay_status(", "fx.post(", "fx.refresh(", "ebay_upload_csv"):
        assert banned not in src, banned


def test_button_is_registered_for_badge():
    assert '"badge": "sold_restock"' in _SRC, "残数を出すボタンとして登録されていない"


def test_panel_counts_and_paints():
    assert "d['restock']=SR.count_workload()" in _SRC, "同じ subprocess で数えていない"
    assert '"sold_restock": sr_txt' in _SRC, "ヒントに出していない"
    assert '"sold_restock": bool(sr.get("actionable") or sr.get("unknown"))' in _SRC
