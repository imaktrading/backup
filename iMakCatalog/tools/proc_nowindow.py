# -*- coding: utf-8 -*-
"""外のプログラムを呼ぶ時に窓を出さないための小道具 (2026-09-24).

なぜ: 予約タスク (pythonw) から `tasklist` / `powershell` / `reg` のような
      コンソールのプログラムを呼ぶと、既定の端末 (Windows Terminal) が一瞬開いて
      **作業中の前面を奪う**。ユーザー報告「ちらちらとうっとうしい」
      (依頼 `iMak_data/inventory/requests/2026-09-24_resume_after_boot_window_flash.md`
       は在庫くん宛てだが、こちらにも同じ形が在った)。

使い方:
    from proc_nowindow import NO_WINDOW, pid_alive
    subprocess.run(cmd, **NO_WINDOW)        # 窓を出さない
    if pid_alive(pid): ...                  # tasklist を呼ばずに生死を見る
"""
from __future__ import annotations

import os
import subprocess
import sys

# Windows だけ。他の OS では空 (渡しても害が無いように)
NO_WINDOW: dict = ({"creationflags": subprocess.CREATE_NO_WINDOW}
                   if sys.platform == "win32" and hasattr(subprocess, "CREATE_NO_WINDOW")
                   else {})


def pid_alive(pid: int) -> bool:
    """そのプロセスがまだ生きているか。外のコマンドを呼ばない (窓が出ない)."""
    if pid <= 0:
        return False
    if sys.platform != "win32":
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False
    import ctypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259
    k = ctypes.windll.kernel32
    h = k.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return False
    try:
        code = ctypes.c_ulong()
        if not k.GetExitCodeProcess(h, ctypes.byref(code)):
            return False
        return code.value == STILL_ACTIVE
    finally:
        k.CloseHandle(h)
