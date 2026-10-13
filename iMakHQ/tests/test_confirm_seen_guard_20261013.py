# -*- coding: utf-8 -*-
"""目視の画面が見えていない間の確定を受け付けない (2026-10-13 補URL③ 補0本の2回目)。"""
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import psa_resource_confirm as P  # noqa: E402


def test_seen_check():
    ok, line = P.seen_check(json.dumps({"open_ms": 180000, "visible_ms": 90000, "acts": 40}))
    assert ok and "受けた" in line
    assert not P.seen_check(json.dumps({"open_ms": 180000, "visible_ms": 0, "acts": 1}))[0]     # 裏に隠れていた
    assert not P.seen_check(json.dumps({"open_ms": 180000, "visible_ms": 60000, "acts": 0}))[0]  # 人が押していない
    assert not P.seen_check(None)[0]                                                            # 画面以外から
    assert not P.seen_check("壊れた")[0]


def _post(url, headers):
    req = urllib.request.Request(url, data=b'{"x":1}', headers=dict({"Content-Type": "application/json"}, **headers))
    try:
        return urllib.request.urlopen(req, timeout=5).status
    except urllib.error.HTTPError as e:
        return e.code


def test_server_refuses_then_accepts(monkeypatch):
    monkeypatch.setenv("IMAK_NO_BROWSER", "1")
    monkeypatch.setenv("IMAK_REVIEW_PORT", "18799")
    out = {}
    th = threading.Thread(target=lambda: out.update(r=P._serve_confirm(b"<html><body>x</body></html>",
                                                                       lambda d: d, 20)))
    th.start()
    time.sleep(1.0)
    url = "http://127.0.0.1:18799/confirm"
    page = urllib.request.urlopen("http://127.0.0.1:18799/", timeout=5).read()
    assert b"X-Seen" in page                                       # 見張りのスクリプトが入っている
    assert _post(url, {}) == 409                                   # 見え方なし = 断る
    assert _post(url, {"X-Seen": json.dumps({"visible_ms": 0, "acts": 3})}) == 409
    assert _post(url, {"X-Seen": json.dumps({"open_ms": 9000, "visible_ms": 8000, "acts": 2})}) == 200
    th.join(10)
    assert out["r"] == {"x": 1}
