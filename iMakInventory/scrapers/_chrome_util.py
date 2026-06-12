"""Chrome 本体バージョン検出 (undetected_chromedriver の version_main 用).

2026-06-13: mercari/amazon driver が `version_main=148` ハードコードのまま Chrome 本体が
v149 に自動更新 → chromedriver 148 が chrome 149 に接続できず
「SessionNotCreatedException: cannot connect to chrome」を頻発させた事故の恒久対策。
インストール済み Chrome の major version を毎回検出して uc に渡すことで、 Chrome 自動更新
(149→150...) にも自動追従し、 version 固定の陳腐化を構造的に防ぐ。
"""
from __future__ import annotations

from typing import Optional

_cache: dict = {"detected": False, "major": None}


def detect_chrome_major() -> Optional[int]:
    """インストール済み Chrome の major version を返す (例 149)。

    検出できなければ None (= uc の自動検出に委ねる)。 プロセス内で一度だけ検出しキャッシュ。
    """
    if _cache["detected"]:
        return _cache["major"]
    _cache["detected"] = True
    major = None
    try:
        import winreg  # noqa: PLC0415  (Windows 専用)
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                k = winreg.OpenKey(hive, r"Software\Google\Chrome\BLBeacon")
                ver, _ = winreg.QueryValueEx(k, "version")
                winreg.CloseKey(k)
                major = int(str(ver).split(".")[0])
                break
            except OSError:
                continue
    except Exception:
        major = None
    _cache["major"] = major
    return major
