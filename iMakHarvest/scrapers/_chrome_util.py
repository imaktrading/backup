"""_chrome_util - Chrome 実バージョン自動検出 (= version_main ハードコード禁止).

グローバル CLAUDE.md (2026-06-14 制定): version_main を数値ハードコードするな。
Chrome 自動更新で固定値が陳腐化 → undetected_chromedriver が誤ドライバを掴み不安定 /
起動時に正しいドライバを fetch しに行き通信断で死ぬ (= 2026-06 の 2 日間事故)。

参照実装: iMakInventory/scrapers/_chrome_util.py:detect_chrome_major() と同方式。
全 create_driver は `version_main = detect_chrome_major() or <fallback定数>` で使う。
"""
from __future__ import annotations

import os
import subprocess
from typing import Optional


def detect_chrome_major() -> Optional[int]:
    """実機 Chrome の major version を返す (= registry → chrome.exe)。 失敗時 None.

    呼び出し側は `detect_chrome_major() or CHROME_VERSION_MAIN` で fallback を持つこと。
    """
    # 1) registry BLBeacon (最も確実・高速)
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
    # 2) chrome.exe の ProductVersion
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
