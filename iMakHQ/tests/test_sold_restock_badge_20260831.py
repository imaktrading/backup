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
    # ★2026-09-03 (後): 青 = **押さないと減らない残件がある**。
    #   ユーザーは青いものしか押さないので、黒にすると永遠に押されない。
    # ★2026-09-15: 補充は夜が送るようになった (1aedc64)。夜が動いている日は黒、止まった日だけ青
    #   (補URL 夜間検索と同じ決まり)。
    assert '"sold_restock": bool(sr.get("actionable") or sr.get("unknown")) and not _auto' in _SRC


def test_hint_does_not_claim_the_button_sends():
    """★2026-09-15: ボタンは一覧だけ。「残り N件 — 今回 全部 送ります」と書くと押しても減らない。"""
    i = _SRC.index('sr_txt = (("\\n夜に %d件 送ります (押すと一覧だけ)"')
    seg = _SRC[i - 400:i + 300]
    assert 'todo_line("sold_restock"' not in seg, "『残り N件 — 今回 送ります』に戻っている"
    assert "押すと一覧だけ" in seg
