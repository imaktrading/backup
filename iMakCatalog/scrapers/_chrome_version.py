"""インストール済 Chrome の major version を検出する共有ヘルパー.

2026-06-14 新設 (orphan chrome 一掃の Catalog 側点検)。

背景:
  各 scraper が `uc.Chrome(version_main=148)` 等で **Chrome major を手動 pin** していた。
  Chrome は自動更新するため (例 148→149)、pin が stale になると chromedriver mismatch →
  `uc.Chrome()` 構築が session 作成途中で失敗 → 起動済 chrome/chromedriver が **orphan** 化する。
  (driver 変数未代入で finally: driver.quit() も効かない経路)。

対策:
  version_main を **インストール済 Chrome から自動検出** して渡す。これで Chrome 更新に追従し、
  mismatch 構築crash → orphan を構造的に防ぐ。検出失敗時は None を返し、
  undetected_chromedriver 本体の自動検出に委ねる (= 従来 fallback と同等、害なし)。

使い方:
  from _chrome_version import installed_chrome_major
  uc.Chrome(options=opts, version_main=installed_chrome_major())
"""
from __future__ import annotations

import os
import re
import subprocess

# 窓を出さない (予約タスクから呼ぶと端末が一瞬開いて前面を奪う。2026-09-24)
_NO_WINDOW = ({"creationflags": subprocess.CREATE_NO_WINDOW}
              if hasattr(subprocess, "CREATE_NO_WINDOW") else {})


def installed_chrome_major(default: int | None = None) -> int | None:
    """インストール済 Chrome の major version (int) を返す。検出不能なら default。

    検出順 (Windows):
      1) レジストリ HKLM/HKCU の BLBeacon version
      2) chrome.exe の ProductVersion (Program Files / LocalAppData)
    いずれも失敗で default (既定 None = uc 本体の自動検出に委ねる)。
    """
    # 1) registry
    for hive in ("HKLM", "HKCU"):
        try:
            out = subprocess.run(
                ["reg", "query",
                 fr"{hive}\Software\Google\Chrome\BLBeacon", "/v", "version"],
                capture_output=True, text=True, timeout=5, **_NO_WINDOW,
            ).stdout
            m = re.search(r"version\s+REG_SZ\s+(\d+)\.", out)
            if m:
                return int(m.group(1))
        except Exception:
            pass
    # 2) chrome.exe ProductVersion (PowerShell 経由)
    candidates = [
        os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"),
                     "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                     "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""),
                     "Google", "Chrome", "Application", "chrome.exe"),
    ]
    for path in candidates:
        if path and os.path.exists(path):
            try:
                out = subprocess.run(
                    ["powershell", "-NoProfile", "-Command",
                     f"(Get-Item '{path}').VersionInfo.ProductVersion"],
                    capture_output=True, text=True, timeout=8, **_NO_WINDOW,
                ).stdout.strip()
                m = re.match(r"(\d+)\.", out)
                if m:
                    return int(m.group(1))
            except Exception:
                pass
    return default


if __name__ == "__main__":
    print("installed_chrome_major =", installed_chrome_major())
