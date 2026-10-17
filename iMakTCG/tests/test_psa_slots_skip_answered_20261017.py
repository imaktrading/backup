# -*- coding: utf-8 -*-
"""B-20261017-014: 見送り済み・目視で決めたカードが出品中の cert は枠を選ぶ前に外す (枠を取らない)。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import psa_to_csv as M   # noqa: E402

SRC = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "psa_to_csv.py"),
           encoding="utf-8").read()


def test_passed_certs_kept_in_order():
    passed = {"174800247": {"reason": "lot"}, "142545172": {"reason": "other"}}
    assert M.passed_certs_now(["1", "142545172", "2", "174800247"], passed) == ["142545172", "174800247"]


def test_passed_unreadable_drops_nothing(monkeypatch):
    import builtins
    real = builtins.__import__

    def boom(name, *a, **k):
        if name == "post_psa_review":
            raise ImportError("x")
        return real(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", boom)
    assert M.passed_certs_now(["1", "2"]) == []


def test_preflight_uses_answered_pid_and_logs_both_lines_even_zero():
    assert "answered_pid_for_cert(_c)" in SRC
    assert '_drop["LIVE-DUP-ANSWERED"] = _dup_answered' in SRC
    assert '_drop["PASSED"] = _passed_drop' in SRC
    assert 'if not _cs and _st not in ("PASSED", "LIVE-DUP-ANSWERED")' in SRC
