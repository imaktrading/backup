# -*- coding: utf-8 -*-
"""読むためだけのページは、拡張に「前に出さない窓」で開いてもらう (2026-10-15 ユーザー
「Cpass の窓の件、分からないように開けて閉じれないの？」)。拾われなければ今までの開き方。"""
import datetime as dt
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
import ext_open as EO  # noqa: E402


def test_taken_by_extension(tmp_path):
    p = str(tmp_path / "req.json")
    calls = []

    def sleep(_s):
        if not calls:
            calls.append(EO.take(path=p))         # 拡張が拾った
    assert EO.ask("https://x/#imak-ship", fallback=lambda u: calls.append("fb"), path=p, wait=9, sleep=sleep) == "ext"
    assert calls == [["https://x/#imak-ship"]]


def test_fallback_when_not_taken(tmp_path):
    p = str(tmp_path / "req.json")
    got = []
    assert EO.ask("https://y", fallback=got.append, path=p, wait=6, sleep=lambda s: None) == "fallback"
    assert got == ["https://y"] and json.load(open(p, encoding="utf-8")) == []


def test_stale_request_is_not_taken(tmp_path):
    p = str(tmp_path / "req.json")
    old = (dt.datetime.now() - dt.timedelta(minutes=10)).isoformat()
    json.dump([{"id": "1", "url": "https://z", "at": old, "taken": ""}], open(p, "w", encoding="utf-8"))
    assert EO.take(path=p) == []


def test_extension_polls_and_opens_unfocused():
    bg = open(os.path.join(HERE, "..", "tools", "sellerhub_grab", "background.js"), encoding="utf-8").read()
    assert "/api/ext/open" in bg and "focused: false" in bg and 'state: "normal"' in bg
