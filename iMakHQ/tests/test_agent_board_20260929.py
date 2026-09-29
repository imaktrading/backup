# -*- coding: utf-8 -*-
"""担当ボード (tools/agent_board.py) — 会話記録から 状態・今・住所 を読む部分 (2026-09-29)。"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import agent_board as AB  # noqa: E402

NOW = dt.datetime(2026, 9, 29, 8, 30, 0)


def _utc(local):
    """この PC の時刻 → 記録の書き方 (UTC の Z)。"""
    return local.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _tool(ts, name, **inp):
    return {"type": "assistant", "timestamp": _utc(ts),
            "message": {"content": [{"type": "tool_use", "name": name, "input": inp}]}}


def _text(ts, text):
    return {"type": "assistant", "timestamp": _utc(ts), "message": {"content": [{"type": "text", "text": text}]}}


def _prompt(ts, text):
    return {"type": "user", "timestamp": _utc(ts), "message": {"content": text}}


def test_url_comes_from_bridge_session_line():
    s = AB.summarize([{"type": "bridge-session", "bridgeSessionId": "cse_01ABCdef"}], NOW)
    assert s["url"] == "https://claude.ai/code/session_01ABCdef"


def test_now_is_last_tool_description_while_working():
    lines = [_prompt(NOW - dt.timedelta(minutes=10), "やって"),
             _tool(NOW - dt.timedelta(minutes=2), "Bash", command="ls", description="一覧を見る")]
    s = AB.summarize(lines, NOW)
    assert s["now"] == "一覧を見る"
    assert AB.state_of("busy", s) == "busy"
    assert s["since_prompt"] == NOW - dt.timedelta(minutes=10)


def test_question_at_end_is_waiting_for_reply():
    lines = [_prompt(NOW - dt.timedelta(minutes=5), "どう?"),
             _text(NOW - dt.timedelta(minutes=4), "結果です。\n\nこの形でよいですか？")]
    s = AB.summarize(lines, NOW)
    assert s["asked"] is True
    assert AB.state_of("idle", s) == "ask"
    assert s["now"] == "結果です。"


def test_plain_finish_is_idle_and_tool_result_is_not_a_prompt():
    lines = [_prompt(NOW - dt.timedelta(minutes=9), "やって"),
             {"type": "user", "timestamp": _utc(NOW - dt.timedelta(minutes=8)),
              "message": {"content": [{"type": "tool_result", "content": "ok"}]}},
             _text(NOW - dt.timedelta(minutes=7), "終わりました。")]
    s = AB.summarize(lines, NOW)
    assert AB.state_of("idle", s) == "idle"
    assert s["since_prompt"] == NOW - dt.timedelta(minutes=9)   # 道具の結果で上書きしない


def test_activity_buckets_last_60_minutes_old_to_new():
    lines = [_tool(NOW - dt.timedelta(minutes=1), "Read", file_path="C:/a/b.py"),
             _tool(NOW - dt.timedelta(minutes=2), "Read", file_path="C:/a/c.py"),
             _tool(NOW - dt.timedelta(minutes=58), "Grep"),
             _tool(NOW - dt.timedelta(minutes=90), "Grep")]              # 60分より前は数えない
    s = AB.summarize(lines, NOW)
    assert len(s["act"]) == 12
    assert s["act"][-1] == 2 and s["act"][0] == 1 and sum(s["act"]) == 3


def test_sheet_round_trip_and_stale():
    rows = [{"name": "💻LAPTOP", "state": "busy", "now": "巡回", "since": "2026-09-29T08:20:00",
             "started": "2026-09-29T05:00:00", "url": "https://claude.ai/code/session_x",
             "act": [0] * 11 + [3], "where": "iMak_inventory"}]
    grid = AB.to_sheet_rows(rows, "2026-09-29T08:25:00")
    fresh = AB.from_sheet_rows(grid, NOW)
    assert fresh["stale"] is False and fresh["rows"][0]["act"][-1] == 3
    assert fresh["rows"][0]["url"].endswith("session_x")
    old = AB.from_sheet_rows(grid, NOW + dt.timedelta(minutes=30))
    assert old["stale"] is True
    assert AB.from_sheet_rows([], NOW)["stale"] is True


def test_shortcut_to_roster_entry():
    args = (r'-w new new-tab --title "ADV-web" -d "C:\dev\iMak\iMakAdvisor" cmd /k '
            r'C:\dev\iMak_data\tools\claude_rc.cmd C:\dev\iMak\iMakAdvisor ADV')
    r = AB.parse_shortcut("Claude ADV", args, "C:/x/Claude ADV.lnk")
    assert r == {"key": "ADV", "label": "ADV", "folder": r"C:\dev\iMak\iMakAdvisor", "lnk": "C:/x/Claude ADV.lnk"}
    assert AB.parse_shortcut("メモ帳", "notepad.exe", "x") is None


def test_merge_roster_marks_open_and_adds_closed():
    roster = [{"key": "HQ", "label": "HQ", "folder": r"C:\dev\iMak\iMakHQ", "lnk": "a"},
              {"key": "ADV", "label": "ADV", "folder": r"C:\dev\iMak\iMakAdvisor", "lnk": "b"}]
    rows = [{"name": "🤖HQ", "state": "busy", "cwd": "C:/dev/iMak/iMakHQ/"}]
    out = AB.merge_roster(rows, roster)
    assert out[0]["key"] == "HQ" and out[0]["state"] == "busy"
    assert [(r["key"], r["state"]) for r in out[1:]] == [("ADV", "off")]


def test_rc_in_cmdlines_sees_window_still_starting():
    lines = [r"cmd /k C:\dev\iMak_data\tools\claude_rc.cmd C:\dev\iMak\iMakAdvisor ADV", None, "cmd /c foo.bat"]
    assert AB.rc_in_cmdlines(r"C:\dev\iMak\iMakAdvisor", lines) is True
    assert AB.rc_in_cmdlines(r"C:\dev\iMak\iMakAdv", lines) is False       # 途中まで同じ名前は別物
    assert AB.rc_in_cmdlines(r"C:\dev\iMak\iMakHQ", lines) is False
