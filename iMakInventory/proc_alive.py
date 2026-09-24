"""pid が生きているか — 外のコマンド (tasklist / powershell) を使わずに調べる.

2026-09-24 ADV 依頼 resume_after_boot_window_flash: pythonw から tasklist を呼ぶと、そのたびに
既定の端末 (Windows Terminal) が一瞬開いて作業中の画面から前面を奪っていた (1分おき)。
Windows API (OpenProcess + GetExitCodeProcess) で直接見るので窓は出ない。

★ os.kill(pid, 0) は Windows では TerminateProcess になる (= 殺してしまう) ので使わない。
"""
from __future__ import annotations

import os
import sys
from typing import Optional

_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_STILL_ACTIVE = 259
_ERROR_ACCESS_DENIED = 5
_ERROR_INVALID_PARAMETER = 87   # そんな pid は無い


def pid_alive(pid: int) -> Optional[bool]:
    """True=生きている / False=いない / None=判定できない."""
    if not isinstance(pid, int) or pid <= 0:
        return False
    if sys.platform != "win32":
        try:
            os.kill(pid, 0)          # POSIX の signal 0 は存在確認だけ (終了させない)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except Exception:
            return None
    try:
        import ctypes  # noqa: PLC0415
        from ctypes import wintypes  # noqa: PLC0415
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        k32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        k32.CloseHandle.argtypes = (wintypes.HANDLE,)
        h = k32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            err = ctypes.get_last_error()
            if err == _ERROR_ACCESS_DENIED:
                return True              # 居るが覗けない (別ユーザーのプロセス等)
            if err == _ERROR_INVALID_PARAMETER:
                return False
            return None
        try:
            code = wintypes.DWORD()
            if not k32.GetExitCodeProcess(h, ctypes.byref(code)):
                return None
            return code.value == _STILL_ACTIVE   # 終了済みでも handle が残っていれば開ける → 終了コードで見る
        finally:
            k32.CloseHandle(h)
    except Exception:
        return None
