# -*- coding: utf-8 -*-
"""出品くん Console の版 (2026-09-16 制定)。

数え方 (ユーザー「ver管理も」):
  0.x … 旧 出品くん (control_panel.py) と併用する移行期間。新画面だけでは仕事が終わらない
  1.0 … **旧パネルの全ボタンが新画面で押せる**ようになった時。ここで初めて「移行できた」と言う
  以降 … 1.1, 1.2 … 新画面の機能追加

版を上げる時は CHANGELOG.md に1行足す。旧 出品くん (control_panel.py) は版を振らない
(触らないから)。画面の右上に「版 · git の短縮 hash」を出し、どの版が動いているかを常に見せる。
"""
import os
import subprocess

VERSION = "0.4.1"
RELEASED = "2026-09-16"
HERE = os.path.dirname(os.path.abspath(__file__))

# 押せない理由 (移行の残り作業)。control_panel の script の形から判定する
BLOCK_REASONS = (
    ("custom_buttons", "ウィザード画面が要る"),
)


def why_not_runnable(script):
    """この画面から押せない理由 (押せるなら空文字)。runnable() と同じ条件を人の言葉で返す。"""
    for key, why in BLOCK_REASONS:
        if script.get(key):
            return why
    return ""


def git_commit():
    try:
        r = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=HERE,
                           capture_output=True, text=True, timeout=10,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return (r.stdout or "").strip()
    except (OSError, subprocess.SubprocessError):
        return ""
