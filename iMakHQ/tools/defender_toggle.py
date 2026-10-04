# -*- coding: utf-8 -*-
"""Windows Defender の検査の対象外 (C:\dev) の ON / OFF — 神風の状態の1行のボタン (2026-10-04)。

★ユーザー「ここにボタン付けてくれない？ON/OFFで。わすれちゃうから」。
  変えるには管理者が要る → 管理者の PowerShell (defender_toggle.ps1) を起こす (Windows の確認が出る)。
  神風は管理者でないので Defender の設定を読めない → ps1 が書く控え (defender_exclusion.json) を読む。
"""
import json
import os
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = r"C:/dev/iMak_data/hq/defender_exclusion.json"
PS1 = os.path.join(HERE, "defender_toggle.ps1")


def status(path=STATE):
    """{"on": True/False/None, "at": 最後に切り替えた時刻}。控えが無ければ on=None (分からない)。"""
    try:
        with open(path, encoding="utf-8-sig") as f:
            d = json.load(f)
        return {"on": bool(d.get("on")), "at": d.get("at") or ""}
    except (OSError, ValueError):
        return {"on": None, "at": ""}


def elevated_command(on):
    """管理者の PowerShell で ps1 を動かすコマンド (純関数)。"""
    inner = f"-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File \"{PS1}\" {'on' if on else 'off'}"
    return ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command",
            f"Start-Process powershell -Verb RunAs -WindowStyle Hidden -ArgumentList '{inner}'"]


def request(on):
    """切り替えを頼む (Windows の確認が出る)。結果は数秒後に status() で分かる。"""
    subprocess.Popen(elevated_command(on), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return {"ok": True}
