# -*- coding: utf-8 -*-
"""画面 (HTML・スプシの URL) をユーザーのブラウザで開く — 唯一の口 (2026-10-04)。

★KAGOYA 移管 段階B: 神風のボタンを KAGOYA で動かすと、webbrowser.open は KAGOYA の画面で開いて
  ユーザーには見えない。KAGOYA の側 (IMAK_NO_BROWSER=1) では開かずに合図の行を出し、
  家の kagoya_button が結果のファイルを取り込んだ後にその行の物を家のブラウザで開く。
  家で動いている時は今までどおりその場で開く。

    from home_open import open_for_user
    open_for_user(r"C:/dev/iMak_data/hq/offer_calc.html")    # ファイル
    open_for_user("https://docs.google.com/...")             # URL
"""
import os
import webbrowser
from pathlib import Path

MARK = "[家で開く] "


def open_for_user(target):
    """target (ファイルのパス / file:// / http(s) の URL) を開く。KAGOYA では合図の行を出すだけ。"""
    t = str(target)
    if os.environ.get("IMAK_NO_BROWSER"):
        print(MARK + t, flush=True)
        return
    webbrowser.open(_uri(t))


def _uri(t):
    if t.startswith(("http://", "https://", "file:")):
        return t
    return Path(t).resolve().as_uri()


def targets_in(lines):
    """出力の行 → 家で開く物の一覧 (重複なし・出てきた順) (純関数)。"""
    out = []
    for ln in lines:
        s = ln.strip()
        if s.startswith(MARK.strip()):
            t = s[len(MARK.strip()):].strip()
            if t and t not in out:
                out.append(t)
    return out


def open_targets(targets):
    """家で開く。ファイルが無い物は開かずに知らせる (取り込めていない)。"""
    for t in targets:
        if not t.startswith(("http://", "https://")) and not os.path.exists(t.replace("file:///", "")):
            print(f"⚠️ 開く画面が家に届いていません: {t}", flush=True)
            continue
        webbrowser.open(_uri(t))
