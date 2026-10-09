# -*- coding: utf-8 -*-
"""定期処理の点検 (2026-10-06)。あるべき姿の台帳と実物を突き合わせ、異常を担当に知らせる。

経緯: 神風の定期タブはこの PC の Windows 予約だけを出しており、夜の束・KAGOYA・LAPTOP が抜け、
移設・廃止した予約 33本が「停止中」として並んでいた。異常を誰にも知らせていなかった。
"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

import schedule_audit as A                                      # noqa: E402

NOW = dt.datetime(2026, 10, 7, 8, 0)


def _exp(name="T", where="home", max_age_h=3, owner="HQ"):
    return {"name": name, "where": where, "owner": owner, "max_age_h": max_age_h}


def test_正常():
    st, _ = A.judge(_exp(), {"state": "Ready", "last": "2026-10-07T07:00:00", "result": 0}, NOW)
    assert st == "ok"


def test_見つからない():
    assert A.judge(_exp(), None, NOW)[0] == "missing"


def test_あるべき姿では動くはずなのに止まっている():
    assert A.judge(_exp(), {"state": "Disabled", "last": "2026-10-07T07:00:00", "result": 0}, NOW)[0] == "disabled"


def test_前回失敗():
    st, why = A.judge(_exp(), {"state": "Ready", "last": "2026-10-07T05:30:00", "result": 1}, NOW)
    assert st == "failed" and "結果 1" in why


def test_間隔を過ぎても動いていない():
    assert A.judge(_exp(max_age_h=3), {"state": "Ready", "last": "2026-10-07T01:00:00", "result": 0}, NOW)[0] == "stale"


def test_実行中は異常にしない():
    assert A.judge(_exp(), {"state": "Running", "last": "2026-10-06T01:00:00", "result": 267009}, NOW)[0] == "running"


def test_前の回が長引いて見送りは失敗にしないが_間隔切れは拾う():
    assert A.judge(_exp(), {"state": "Ready", "last": "2026-10-07T07:00:00", "result": A.OVERLAP}, NOW)[0] == "overlap"
    assert A.judge(_exp(), {"state": "Ready", "last": "2026-10-06T07:00:00", "result": A.OVERLAP}, NOW)[0] == "stale"


CONF = {
    "expected": [_exp("H1"), _exp("K1", "kagoya"), _exp("night", "job_queue", 30),
                 _exp("監視", "laptop", 11, "監視くん")],
    "retired": {"OLD": "LAPTOP に移設"},
    "ask": {"Q": {"owner": "抽出くん", "q": "どこで回していますか"}},
}


def test_全体_止めた物は異常に出さず台帳に無い予約は拾う():
    home = {"H1": {"state": "Ready", "last": "2026-10-07T07:30:00", "result": 0},
            "OLD": {"state": "Disabled", "last": "2026-09-26T00:00:00", "result": 0},
            "Q": {"state": "Disabled", "last": "2026-10-01T00:00:00", "result": 0},
            "NEW": {"state": "Ready", "last": "2026-10-07T07:00:00", "result": 0}}
    kag = {"K1": {"state": "Ready", "last": "2026-10-07T07:00:00", "result": 1}}
    jobq = {"night": {"last_ok": "2026-10-06T22:00:00", "last_rc": 0, "pid": None}}
    res = A.audit(CONF, home, kag, jobq, dt.datetime(2026, 10, 7, 2, 55), NOW)
    st = {r["name"]: r["status"] for r in res["rows"]}
    assert st == {"H1": "ok", "K1": "failed", "night": "ok", "監視": "ok", "Q": "ask", "NEW": "unknown_task"}
    assert [r["name"] for r in res["retired"]] == ["OLD"]


def test_KAGOYAに繋がらない時は確かめられないと出す():
    res = A.audit(CONF, {}, None, {}, None, NOW)
    k = [r for r in res["rows"] if r["name"] == "K1"][0]
    assert k["status"] == "unknown"


def test_監視くんの最後の巡回が11時間より前なら止まっている():
    res = A.audit(CONF, {}, {}, {}, dt.datetime(2026, 10, 6, 20, 0), NOW)
    assert [r for r in res["rows"] if r["name"] == "監視"][0]["status"] == "stale"


def test_同じ異常は1回だけ知らせ_直るまで出し直さない():
    rows = [{"name": "K1", "status": "failed", "owner": "カタログ", "where": "kagoya", "why": "x"},
            {"name": "H1", "status": "ok", "owner": "HQ", "where": "home", "why": "x"}]
    assert list(A.to_notify(rows, {}, NOW)) == ["カタログ"]
    old = {"K1|failed": "2026-10-01T07:00:00"}           # 何日たっても出し直さない (2026-10-09 問題 C)
    assert A.to_notify(rows, old, NOW) == {}
    assert list(A.to_notify(rows, old, NOW, renotify_h=24)) == ["カタログ"]   # 間隔を入れた時だけ出し直す


def test_知らせの本文は既知と未回答を分けて書く():
    body = A.note_body("カタログ", [{"name": "K1", "where": "kagoya", "why": "前回 失敗"}], NOW)
    assert "## 既に判明していること" in body and "## 聞きたいこと" in body and "K1" in body


def test_台帳の実物が読めて_担当の置き場が全部ある():
    import json
    conf = json.load(open(A.EXPECTED, encoding="utf-8"))
    owners = conf["owners"]
    for e in conf["expected"]:
        assert e["owner"] in owners and e["where"] in ("home", "kagoya", "job_queue", "laptop")
    for q in conf["ask"].values():
        assert q["owner"] in owners
    names = [e["name"] for e in conf["expected"]] + list(conf["retired"]) + list(conf["ask"])
    assert len(names) == len(set(names)), "同じ予約が二重に載っている"


def test_作ったばかりで初回待ちは異常にしない_次回が無ければ拾う():
    a = {"state": "Ready", "last": "1999-11-30T00:00:00", "result": A.NEVER, "next": "2026-10-07T09:00:00"}
    assert A.judge(_exp(), a, NOW)[0] == "never"
    assert "never" not in A.BAD
    b = dict(a, next="")
    assert A.judge(_exp(), b, NOW)[0] == "stale"


def test_夜の束に足したばかりの仕事は初回待ち_定義にも無ければ見つからない():
    conf = {"expected": [_exp("new_job", "job_queue", 30)], "retired": {}, "ask": {}}
    res = A.audit(conf, {}, {}, {"_defined": ["new_job"]}, None, NOW)
    assert res["rows"][0]["status"] == "never"
    res = A.audit(conf, {}, {}, {"_defined": []}, None, NOW)
    assert res["rows"][0]["status"] == "missing"


def test_夜の束でany_rc_okの仕事は結果コードが0以外でも正常():
    conf = {"expected": [_exp("weekly", "job_queue", 200)], "retired": {}, "ask": {}}
    st = {"weekly": {"last_ok": "2026-10-07T06:00:00", "last_rc": 10, "pid": None}}
    res = A.audit(conf, {}, {}, dict(st, _defined=["weekly"], _any_rc_ok=["weekly"]), None, NOW)
    assert res["rows"][0]["status"] == "ok"
    res = A.audit(conf, {}, {}, dict(st, _defined=["weekly"], _any_rc_ok=[]), None, NOW)
    assert res["rows"][0]["status"] == "failed"
