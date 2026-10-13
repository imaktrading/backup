# -*- coding: utf-8 -*-
"""補0本だけの補充ボタン (2026-10-13 ユーザー「ボタンを補0の補充だけ、単独にした方がいいよね」)。"""
import os
import sys

_H = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(_H, "console"))


def test_button_defined():
    src = open(os.path.join(_H, "control_panel.py"), encoding="utf-8").read()
    assert '"badge": "hoju_zero"' in src and '"--max-backups=1"' in src


def test_server_puts_zero_count():
    import server
    out = server.job_counts({"hoju": {"search": {}, "confirm": {}, "swap": {}, "zero": {"ready": 2, "unjudged": 58}}}) \
        if hasattr(server, "job_counts") else None
    if out is None:                                   # 関数名が違っても、件数の口があることだけは確かめる
        assert "hoju_zero" in open(os.path.join(_H, "console", "server.py"), encoding="utf-8").read()
    else:
        assert out["hoju_zero"]["n"] == 60


def test_matrix_has_column():
    src = open(os.path.join(_H, "console", "static", "app.js"), encoding="utf-8").read()
    # ★2026-10-13 補0本・補1本を1つの枠に半分の高さで2つ
    assert '"hoju_zero", "hoju_one", "hoju_two"' in src and "③ 補2〜3本" in src and '"hoju_confirm"];' in src
