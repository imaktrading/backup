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

VERSION = "0.7.11"
RELEASED = "2026-09-29"
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


# ---------------------------------------------------------------- ボタンごとの版 (2026-10-15)
# ★ユーザー「それぞれのボタンを版管理したら？」「ボタンのプログラムも修正していくわけでしょ？」。
#   人が番号を上げると上げ忘れて当てにならないので、**git の記録から自動で決める**:
#   版 = そのボタンが動かすプログラム (本体 + 同じ置き場から読み込んでいる部品) が最後に直された日と、
#   その日の何回目か。例 "10/14-3"。走行ログの2行目とボタンに出す。
import re as _re
import time as _time

_BTN_VER = {}
_BTN_VER_TTL = 600
_PY_LITERAL_RE = _re.compile(r"[\"']([A-Za-z_][\w]*)\.py[\"']")
_IMPORT_RE = _re.compile(r"^\s*(?:from\s+([A-Za-z_][\w]*)\s+import|import\s+([A-Za-z_][\w]*))", _re.M)


def script_files(script):
    """ボタン → 版を数えるファイル (本体 + 本体が読み込む同じ置き場・iMakeBayAPI の部品) の一覧 (I/O は存在確認のみ)。"""
    cwd = str(script.get("cwd") or "")
    cmd = list(script.get("cmd") or [])
    main = next((c for c in cmd if str(c).endswith(".py")), None)
    if not cwd or not main:
        return []
    path = os.path.normpath(os.path.join(cwd, main))
    if not os.path.isfile(path):
        return []
    dirs = [os.path.dirname(path), os.path.normpath(os.path.join(HERE, "..", "..", "iMakeBayAPI"))]
    out = [path]
    try:
        src = open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return out
    # 読み込む部品 (import) と、子として走らせるプログラム ("psa_resource_gate.py" の様に名前を書いた物)
    names = [a or b for a, b in _IMPORT_RE.findall(src)] + _PY_LITERAL_RE.findall(src)
    for name in names:
        for d in dirs:
            f = os.path.join(d, name + ".py")
            if os.path.isfile(f) and f not in out:
                out.append(f)
                break
    return out


def button_version(script, now=None):
    """ボタンの版 "MM/DD-N" (git に記録が無ければ "")。10分は覚えておく (画面を開くたびに git を呼ばない)。"""
    files = script_files(script)
    if not files:
        return ""
    key = tuple(files)
    now = now or _time.time()
    hit = _BTN_VER.get(key)
    if hit and now - hit[0] < _BTN_VER_TTL:
        return hit[1]
    v = ""
    try:
        r = subprocess.run(["git", "log", "-60", "--format=%cd", "--date=format:%Y-%m-%d", "--"] + files,
                           cwd=HERE, capture_output=True, text=True, timeout=15,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        v = version_from_dates((r.stdout or "").split())
    except (OSError, subprocess.SubprocessError):
        v = ""
    _BTN_VER[key] = (now, v)
    return v


def version_from_dates(dates):
    """git log の日付 (新しい順) → "MM/DD-N" (その日の何回目か)。純関数。"""
    dates = [d for d in dates if d]
    if not dates:
        return ""
    last = dates[0]
    n = sum(1 for d in dates if d == last)
    return "%s/%s-%d" % (last[5:7], last[8:10], n)
