"""予約タスク (pythonw) から console プログラムを呼んで窓を出さない (2026-09-24).

pythonw から tasklist / powershell / schtasks を窓の指定なしで呼ぶと、既定の端末が一瞬開いて
作業中の画面から前面を奪う (resume_after_boot が1分おきに出していた)。
"""
from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 予約タスクから動くコード (control_panel は人が開く GUI なので対象外)
SCHEDULED = [
    ROOT / "run_cycle.py", ROOT / "monitor_listings.py", ROOT / "ledger_lock.py",
    ROOT / "tools" / "resume_after_boot.py", ROOT / "tools" / "drain_pending_takedowns.py",
    ROOT / "ebay_actions" / "sell_feed_uploader.py",
    ROOT.parent / "iMakeBayAPI" / "inventory_monitor" / "run_daily.py",
    ROOT.parent / "iMakeBayAPI" / "inventory_monitor" / "zozo_scraper.py",
]


def _calls_without_flag(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    bad = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if isinstance(f, ast.Attribute) and f.attr in ("run", "Popen", "call", "check_output", "check_call") \
                and isinstance(f.value, ast.Name) and f.value.id == "subprocess":
            if not any(k.arg == "creationflags" for k in node.keywords):
                bad.append(node.lineno)
    return bad


def test_scheduled_code_never_opens_console_window():
    problems = {str(p.name): _calls_without_flag(p) for p in SCHEDULED if p.exists()}
    assert {k: v for k, v in problems.items() if v} == {}


def test_tasklist_not_used_for_liveness():
    for p in SCHEDULED:
        if p.exists():
            assert '"tasklist"' not in p.read_text(encoding="utf-8"), p.name


def test_pid_alive_without_subprocess():
    import subprocess
    from proc_alive import pid_alive
    assert pid_alive(os.getpid()) is True
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    assert pid_alive(child.pid) is False          # 終了済み (handle は残っている) → 死んでいる
    assert pid_alive(0) is False and pid_alive(-1) is False
