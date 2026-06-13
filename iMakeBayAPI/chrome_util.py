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
