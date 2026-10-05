"""神風の担当タブ: KAGOYA の .bat (Catalog.bat) も担当として読み、起動中を見分ける (2026-10-05)。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import agent_board as A  # noqa: E402

CATALOG_BAT = r'''@echo off
title CATALOG
cd /d C:\dev\iMak_catalog\iMakCatalog
if exist "x" (
  "C:\Users\Administrator\.local\bin\claude.exe" --continue --remote-control CATALOG --remote-control-session-name-prefix CATALOG
)
'''


def test_parse_bat_catalog():
    r = A.parse_bat("Catalog", CATALOG_BAT, r"C:\Users\Administrator\Desktop\Catalog.bat")
    assert r == {"key": "CATALOG", "label": "カタログ", "folder": r"C:\dev\iMak_catalog\iMakCatalog",
                 "lnk": r"C:\Users\Administrator\Desktop\Catalog.bat"}


def test_parse_bat_plain_claude_is_not_agent():
    assert A.parse_bat("Claude", '@echo off\ncd /d C:\\dev\n"claude.exe"\n', "C:/x/Claude.bat") is None


def test_bat_running_detected():
    lines = [r'C:\Windows\system32\cmd.exe /c ""C:\Users\Administrator\Desktop\Catalog.bat" "']
    assert A.rc_in_cmdlines(r"C:\dev\iMak_catalog\iMakCatalog", lines,
                            r"C:\Users\Administrator\Desktop\Catalog.bat")
    assert not A.rc_in_cmdlines(r"C:\dev\iMak_catalog\iMakCatalog", lines, "")


def test_parse_json_out_takes_last_json_line():
    assert A.parse_json_out('noise\n[{"name": "CATALOG"}]\n') == [{"name": "CATALOG"}]
    assert A.parse_json_out("no json") is None
