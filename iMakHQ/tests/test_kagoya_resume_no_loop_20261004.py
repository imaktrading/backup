# -*- coding: utf-8 -*-
"""KAGOYA の朝の仕事: 進まないまま落ち続けたら、毎時の再開をやめて要対応にする (2026-10-04)。

ユーザー「むだに LOOP して使うとか、あり得ないよね」(抽出くんのトレジャーが落ちては毎時やり直し、有料 API を浪費)。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
import kagoya_offload as K  # noqa: E402


def test_stops_after_two_resumes_without_progress():
    t = None
    stop, t = K.resume_should_stop(t, "j1", 10)
    assert not stop and t["n"] == 1
    stop, t = K.resume_should_stop(t, "j1", 10)
    assert not stop and t["n"] == 2
    stop, t = K.resume_should_stop(t, "j1", 10)
    assert stop


def test_progress_resets_count():
    stop, t = K.resume_should_stop({"job_id": "j1", "lines": 10, "n": 2}, "j1", 25)
    assert not stop and t["n"] == 1 and t["lines"] == 25


def test_new_job_resets_count():
    stop, t = K.resume_should_stop({"job_id": "j1", "lines": 10, "n": 2}, "j2", 0)
    assert not stop and t["job_id"] == "j2" and t["n"] == 1
