#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Chrome major version 検出ユーティリティ (master 共有版)。

undetected_chromedriver の version_main に数値をハードコードすると、Chrome 本体の
自動更新でズレて SessionNotCreatedException で driver が起動不能になる
(2026-06-13 全worktree横断ルール制定の契機: v148固定 vs Chrome149)。

実 Chrome の major version をレジストリ BLBeacon から検出し、検出失敗時は None
(= uc に自動検出させる) を返す。Inventory/Harvest の scrapers/_chrome_util.py と同方式。

使い方:
    from _chrome_util import detect_chrome_major
    driver = uc.Chrome(options=options, version_main=detect_chrome_major())

★2026-07-30 追加: `silence_chromedriver_console()`
    headless で回していても **chromedriver 自身のコンソール窓 (黒窓) が出る**。
    無人 cron 中に画面へ出っぱなしになり、ユーザーが閉じると子プロセスが道連れで死ぬ
    (dispatch の claude.exe で同型事故。CREATE_NO_WINDOW で対処済)。
    uc.Chrome() を呼ぶ **前に 1 回**呼べば、その process 内の全 driver 起動が窓なしになる。
"""
from __future__ import annotations


def detect_chrome_major():
    """インストール済み Chrome の major version (int) を返す。検出不能なら None。

    None を渡せば undetected_chromedriver が自動検出する(数値ハードコード厳禁)。
    Windows のみレジストリ参照。非 Windows / 失敗時は None。
    """
    try:
        import winreg
    except Exception:
        return None
    for hive in (getattr(winreg, "HKEY_CURRENT_USER", None),
                 getattr(winreg, "HKEY_LOCAL_MACHINE", None)):
        if hive is None:
            continue
        try:
            with winreg.OpenKey(hive, r"Software\Google\Chrome\BLBeacon") as key:
                version, _ = winreg.QueryValueEx(key, "version")
            major = int(str(version).split(".")[0])
            if major > 0:
                return major
        except Exception:
            continue
    return None


def silence_chromedriver_console():
    """chromedriver のコンソール窓 (黒窓) を出さないようにする。冪等・失敗しても無害。

    undetected_chromedriver は `ChromiumService(executable_path)` を **creation_flags 無し**で
    作るため、Windows では driver プロセスにコンソール窓が付く (実測 2026-07-30 05:30 /
    05:58 の `undetected_chromedriver.exe --port=...`)。

    ★selenium 4.41 の `Service.__init__` は `creation_flags` を **`popen_kw` の中**から取る
      (`self.creation_flags = self.popen_kw.pop("creation_flags", 0)`)。トップレベル kwarg で
      渡しても無視されるので、必ず `popen_kw` に入れること (最初これを間違えてテストで検出)。

    ★uc.Chrome() を呼ぶ前に 1 回呼ぶこと。呼び忘れても動作は変わらない (窓が出るだけ)。
    ★窓を消す理由は美観ではない: 無人 cron の窓をユーザーが閉じると、子プロセスが
      0xC000013A で道連れに死ぬ (dispatch の claude.exe で踏んだのと同じ経路)。
    """
    import sys
    if sys.platform != "win32":
        return False
    try:
        import subprocess
        from selenium.webdriver.chromium import service as _svc
    except Exception:
        return False
    cls = _svc.ChromiumService
    if getattr(cls, "_imak_quiet_patched", False):
        return True                       # 冪等 (二重パッチで再帰しない)
    _orig_init = cls.__init__

    def _quiet_init(self, *args, **kwargs):
        popen_kw = dict(kwargs.get("popen_kw") or {})
        popen_kw.setdefault("creation_flags", subprocess.CREATE_NO_WINDOW)  # 呼び手の明示を尊重
        kwargs["popen_kw"] = popen_kw
        _orig_init(self, *args, **kwargs)

    cls.__init__ = _quiet_init
    cls._imak_quiet_patched = True
    return True
