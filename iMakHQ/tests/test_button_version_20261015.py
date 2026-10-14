# -*- coding: utf-8 -*-
"""ボタンごとの版 (2026-10-15 ユーザー「それぞれのボタンを版管理したら？」「ボタンに書かないの？」)。

版 = そのボタンのプログラム (本体 + 読み込む部品 + 子として走らせるプログラム) が最後に直された日と、その日の何回目か。
git の記録から自動で決める (人が番号を上げると上げ忘れる)。ボタンと走行ログの2行目に出す。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "console"))

import version as V  # noqa: E402


def test_version_from_dates():
    assert V.version_from_dates(["2026-10-14", "2026-10-14", "2026-10-13"]) == "10/14-2"
    assert V.version_from_dates([]) == ""


def test_script_files_include_imports_and_child_scripts(tmp_path):
    (tmp_path / "main.py").write_text('import helper\nSTEPS = [("x", ["child.py"])]\n', encoding="utf-8")
    (tmp_path / "helper.py").write_text("", encoding="utf-8")
    (tmp_path / "child.py").write_text("", encoding="utf-8")
    got = [os.path.basename(f) for f in V.script_files({"cwd": str(tmp_path), "cmd": ["python", "main.py"]})]
    assert got == ["main.py", "helper.py", "child.py"]


def test_screen_and_log_show_version():
    c = os.path.join(HERE, "..", "console")
    srv = open(os.path.join(c, "server.py"), encoding="utf-8").read()
    js = open(os.path.join(c, "static", "app.js"), encoding="utf-8").read()
    assert '"ver": btn_ver(s)' in srv and "版: %s" in srv
    assert "bver" in js and "x.ver" in js
