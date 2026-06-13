"""_chrome_util - Chrome 実バージョン自動検出 (= version_main ハードコード禁止).

グローバル CLAUDE.md (2026-06-14): version_main を数値ハードコードするな。
Chrome 自動更新で固定値が陳腐化 → undetected_chromedriver 構築 crash → orphan の温床。
参照: iMakInventory/iMakHarvest/iMakeBayAPI の同名 detect_chrome_major() と同方式。

呼び出し側は `detect_chrome_major() or <fallback定数>` で使う (= 検出失敗時も無回帰)。
"""
from __future__ import annotations

import os
import subprocess
from typing import Optional


def detect_chrome_major() -> Optional[int]:
    """実機 Chrome の major version (= registry → chrome.exe)。 失敗時 None."""
    try:
        import winreg  # noqa: PLC0415
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                k = winreg.OpenKey(hive, r"Software\Google\Chrome\BLBeacon")
                ver, _ = winreg.QueryValueEx(k, "version")
                winreg.CloseKey(k)
                if ver:
                    return int(str(ver).split(".")[0])
            except OSError:
                continue
    except Exception:
        pass
    for p in (
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ):
        try:
            if os.path.exists(p):
                out = subprocess.run(
                    ["powershell", "-NoProfile", "-Command",
                     f"(Get-Item '{p}').VersionInfo.ProductVersion"],
                    capture_output=True, text=True, timeout=10,
                ).stdout.strip()
                if out:
                    return int(out.split(".")[0])
        except Exception:
            continue
    return None
