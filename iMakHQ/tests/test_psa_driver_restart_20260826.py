# -*- coding: utf-8 -*-
"""Chrome のセッションが死んだら作り直して続ける (2026-08-26)。

## 何が起きたか
8/26 19:09 の走行で、3件目の途中に Chrome のセッションが死んだ
(`invalid session id`)。そこから先の **13件が1件ずつ同じエラーで空振り**し、
20件処理するはずが出品できたのは1件だけだった。

セッションが死んだ後は何度呼んでも回復しないので、**気づいて作り直す**しかない。
"""
import os
import sys

_TCG = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                    "iMakTCG")
if _TCG not in sys.path:
    sys.path.insert(0, _TCG)


def _mod():
    import psa_to_csv
    return psa_to_csv


def test_invalid_session_is_dead():
    """実際に出たメッセージ (selenium の InvalidSessionIdException)。"""
    M = _mod()

    class InvalidSessionIdException(Exception):
        pass

    assert M.is_dead_session(InvalidSessionIdException(
        "Message: invalid session id; For documentation on this error, please visit: ..."))


def test_other_dead_signals():
    M = _mod()
    for msg in ("no such window: target window already closed",
                "chrome not reachable",
                "disconnected: not connected to DevTools"):
        assert M.is_dead_session(Exception(msg)), msg


def test_ordinary_errors_are_not_dead():
    """普通の取得失敗で Chrome を作り直さない (無駄に起動し直さない)。"""
    M = _mod()
    for msg in ("Message: no such element: Unable to locate element",
                "timeout: Timed out receiving message from renderer",
                "HTTP 404"):
        assert not M.is_dead_session(Exception(msg)), msg


def test_scrape_reraises_dead_session_so_caller_can_restart():
    """★死んだセッションは握り潰さず投げる。握り潰すと呼び手が気づけない。"""
    src = open(os.path.join(_TCG, "psa_to_csv.py"), encoding="utf-8").read()
    i = src.index("def get_psa_data(")
    body = src[i:i + 12000]
    assert "if is_dead_session(e):" in body and "raise" in body


def test_verify_loop_restarts_the_browser():
    """取得ループが Chrome を作り直して、その cert からやり直すこと。"""
    src = open(os.path.join(_TCG, "psa_to_csv.py"), encoding="utf-8").read()
    i = src.index("取得中(確認用)")
    body = src[i:i + 1500]
    assert "restart_psa_driver" in body
