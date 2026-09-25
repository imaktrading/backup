"""Windows のトースト通知を、巡回とは別のプロセスで出す (2026-09-25).

win10toast を巡回のプロセス内 (threaded=True) で出すと、通知を閉じる時に
`TypeError: WPARAM is simple, so must be an int object (got NoneType)` が出て、
巡回のログに「巡回が落ちました」と偽の記録が残っていた (9/20〜25 に19回。巡回が通知を出した約10秒後)。
さらに 9/25 04:21 には HIGH 完了の3秒後に同じプロセスがヒープ破損 (0xc0000374) で落ちている。
通知は使い捨ての子プロセスに任せ、そこで何が起きても巡回は巻き込まれないようにする。
"""
from __future__ import annotations

import os
import subprocess
import sys

_SCRIPT = (
    "import sys\n"
    "try:\n"
    "    from win10toast import ToastNotifier\n"
    "    ToastNotifier().show_toast(sys.argv[1], sys.argv[2], duration=int(sys.argv[3]), threaded=False)\n"
    "except Exception:\n"
    "    pass\n"
)


def _pythonw() -> str:
    exe = sys.executable
    if exe.lower().endswith("python.exe"):
        cand = exe[:-len("python.exe")] + "pythonw.exe"
        if os.path.exists(cand):
            return cand
    return exe


def show_toast(title: str, body: str, duration: int = 10) -> bool:
    """通知を出す子プロセスを起動して、待たずに戻る。起動できなければ False (巡回は続ける)."""
    if sys.platform != "win32":
        return False
    try:
        subprocess.Popen(
            [_pythonw(), "-c", _SCRIPT, str(title)[:64], str(body)[:250], str(int(duration))],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            close_fds=True,
        )
        return True
    except Exception:
        return False
