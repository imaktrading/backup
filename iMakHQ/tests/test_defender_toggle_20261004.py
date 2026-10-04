# -*- coding: utf-8 -*-
"""神風の状態の1行に Defender の検査の対象外 (C:\dev) の ON/OFF ボタン (2026-10-04 ユーザー「わすれちゃうから」)。"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
import defender_toggle as DT  # noqa: E402


def test_status_reads_state_file(tmp_path):
    p = tmp_path / "s.json"
    assert DT.status(str(p)) == {"on": None, "at": ""}
    p.write_text(json.dumps({"on": True, "at": "2026-10-04T19:00:00"}), encoding="utf-8")
    assert DT.status(str(p)) == {"on": True, "at": "2026-10-04T19:00:00"}


def test_elevated_command_runs_ps1_as_admin():
    cmd = " ".join(DT.elevated_command(True))
    assert "-Verb RunAs" in cmd and "defender_toggle.ps1" in cmd and cmd.rstrip("'").endswith("on")
    assert " off" in " ".join(DT.elevated_command(False))


def test_strip_has_toggle():
    js = open(os.path.join(HERE, "..", "console", "static", "app.js"), encoding="utf-8").read()
    assert "STRIP.defender" in js and "data-defender" in js
