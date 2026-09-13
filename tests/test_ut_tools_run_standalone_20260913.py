# -*- coding: utf-8 -*-
"""UT の道具が **パネルと同じ起動のしかた** で読み込めること (2026-09-13)。

実害: cf303e8 で KEY の判定を `ut_catalog_values` (iMakMercari) に寄せた時、
`ut_identify.py` 側で読み込み先を足し忘れた。テストは conftest 等で iMakMercari を
読み込み先に入れて走るので緑のまま、**🩹 UT 新品 目視特定 は起動すると落ちていた**
(ModuleNotFoundError)。パネルの残件表示も同じ所で落ち「取得できず」になっていた。

ここではテストの読み込み先を使わず、別プロセスで tools/ から素のまま import する。
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parent.parent / "iMakHQ" / "tools"

CODE = (
    "import sys, os\n"
    "sys.path[:] = [p for p in sys.path if 'iMakMercari' not in p and 'tests' not in p]\n"
    "sys.path.insert(0, os.getcwd())\n"
    "import {mod}\n"
    "{check}\n"
    "print('OK')\n"
)


@pytest.mark.parametrize("mod,check", [
    ("ut_identify", "ut_identify._needs_key([''] * 40)"),
    ("ut_key_backfill", "ut_key_backfill.plan([[''] * 40], {})"),
    ("ut_hoju_fill", "ut_hoju_fill.select_targets([[''] * 40])"),
])
def test_imports_like_the_panel_does(mod, check):
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONPATH="")
    r = subprocess.run([sys.executable, "-c", CODE.format(mod=mod, check=check)],
                       cwd=str(TOOLS), capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env, timeout=120)
    assert "OK" in r.stdout, f"{mod} を単体で読み込めない:\n{r.stderr[-1500:]}"
