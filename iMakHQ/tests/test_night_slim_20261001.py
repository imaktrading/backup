# -*- coding: utf-8 -*-
"""夜の束のスリム化 (2026-10-01 全体点検・ユーザー「いい機会だ、全体点検やる！」)。"""
import io
import os

BAT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools", "run_hoju_search.bat")


def _bat():
    return io.open(BAT, encoding="ascii").read()


def test_zero_backup_search_is_resumable():
    """補0本の探索も night_step で囲む。再開のたびに同じ30件を探し直していた (10/01 約1時間)。"""
    b = _bat()
    chk = b.index("night_step.py hoju psa_hoju_fill.search.--limit=30 --check")
    loop = b.index("python -u psa_hoju_fill.py search --limit=30")
    ok = b.index("night_step.py hoju psa_hoju_fill.search.--limit=30 --done 0")
    assert chk < loop < ok
    assert "|| goto :topup" in b[chk:loop]
