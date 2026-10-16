# -*- coding: utf-8 -*-
"""2026-10-17 夜 4:30 の注文の取り込みが CPaSS (ログアウト中) の窓を開いたまま残していた。返事が無ければ開いた窓を閉じる。"""
import datetime as dt
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))


def test_fetch_closes_its_window_on_timeout(monkeypatch):
    import cpass_fees as C
    import mercari_purchases as MP
    closed = []
    monkeypatch.setattr(MP, "_open_quiet", lambda u, w: [111])
    monkeypatch.setattr(MP, "close_windows", lambda hs: closed.extend(hs) or len(hs))
    monkeypatch.setattr(C, "load", lambda path=None: {})
    with pytest.raises(RuntimeError):
        C.fetch(wait=3, sleep=lambda s: None, now=lambda: dt.datetime(2026, 10, 17, 4, 30))
    assert closed == [111]
