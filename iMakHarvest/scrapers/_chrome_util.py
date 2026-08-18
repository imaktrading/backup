"""_chrome_util - Chrome 起動まわりの共通処理 (version 検出 / ウィンドウ非表示).

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


# ---------------------------------------------------------------------------
# ウィンドウ非表示 (= ユーザーの画面を邪魔しない。 2026-08-19 制定)
# ---------------------------------------------------------------------------
# 収集は非 headless が必須 (headless だと件数が 1語15件 → 6件に落ちる) だが、
# 数時間 Chrome が画面に出続けるのは論外。 画面外へ飛ばすのは Windows が可視領域へ
# 引き戻すので効かない (実測: -32000 指定でも L=-7)。 **ウィンドウごと隠す**。
# 描画は `--disable-features=CalculateNativeWinOcclusion` で継続するので件数は落ちない
# (最小化はこれが効かず描画が止まるので使わない)。
#
# ★新しく driver を起こす所を足す時は、 必ず起動直後に hide_browser_window() を呼ぶこと。
_SW_HIDE = 0


def onscreen_requested() -> bool:
    """IMAK_CHROME_ONSCREEN=1 なら 画面に出す (デバッグ用)."""
    return os.environ.get("IMAK_CHROME_ONSCREEN", "").strip() in ("1", "true", "yes")


def hide_browser_window(driver) -> bool:
    """driver のウィンドウを隠す (Windows のみ)。 隠せたら True.

    ウィンドウの特定は **一意なタイトルを自分で付けて探す**
    (PID 経由は chrome の子プロセス構成に依存して当たらないことがある)。
    """
    if os.name != "nt" or onscreen_requested():
        return False
    import ctypes  # noqa: PLC0415
    from ctypes import wintypes  # noqa: PLC0415

    token = f"IMAK_HIDE_{os.getpid()}_{id(driver)}"
    try:
        driver.execute_script("document.title = arguments[0];", token)
    except Exception:  # noqa: BLE001 - about:blank 以外でも失敗したら諦める
        return False

    user32 = ctypes.windll.user32
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _cb(hwnd, _lparam):
        length = user32.GetWindowTextLengthW(hwnd)
        if length:
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            if token in buf.value:
                found.append(hwnd)
        return True

    try:
        user32.EnumWindows(_cb, 0)
        for hwnd in found:
            user32.ShowWindow(hwnd, _SW_HIDE)
    except Exception:  # noqa: BLE001
        return False
    return bool(found)
