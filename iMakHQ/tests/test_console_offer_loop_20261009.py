# -*- coding: utf-8 -*-
"""オファーの件数は 10分おきに数え直す (2026-10-09 ユーザー「オファーを読んでいないのではないか」)。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "console"))
import server as S


def test_offer_loop_is_started_and_counts_offer_only(monkeypatch):
    src = open(S.__file__, encoding="utf-8").read()
    assert "threading.Thread(target=_offer_loop, daemon=True).start()" in src
    assert S.OFFER_EVERY_SEC <= 600
    seen, logs = [], []
    monkeypatch.setattr(S, "refresh_counts", lambda keys=None, wait=False: seen.append(keys))
    monkeypatch.setattr(S, "_log", logs.append)
    monkeypatch.setitem(S.STATE, "counting", False)
    monkeypatch.setitem(S.STATE, "counts", {"offer": {"actionable": 1}})

    def stop(sec):
        if sec == S.OFFER_EVERY_SEC:
            raise KeyboardInterrupt
    monkeypatch.setattr(S.time, "sleep", stop)
    try:
        S._offer_loop()
    except KeyboardInterrupt:
        pass
    assert seen == [["offer"]] and logs == ["📨 オファーを数え直しました: 1件 (10分おき)"]
