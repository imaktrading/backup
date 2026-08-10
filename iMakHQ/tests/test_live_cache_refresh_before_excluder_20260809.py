# -*- coding: utf-8 -*-
"""live cache の鮮度確保は **重複除外より前** に走ること (2026-08-09).

事故:
  重複くん excluder は live cache が 6h より古いと
  「[FATAL] HQ live_listings_cache が使えない → CSV 触らず入稿停止」で
  **除外を丸ごと skip** する。ところが cache を取り直す担当は後段の dup_guard しか
  居なかったため、順序が「excluder は素通り → 重複は後段が拾えた時だけ消える」に
  なっていた。

  2026-08-09 実測: age=23.7h で excluder が skip。重複2件
  (pokemon_tcg:M3-082 / one_piece_tcg:OP05-022) は後段の dup_guard が
  cache を取り直して辛うじて物理除外した。dup_guard が無ければ **重複したまま入稿**。

固定する挙動:
  1. dup_guard に --refresh-cache モードが在る
  2. control_panel がそれを **excluder より前** に呼ぶ
"""
from __future__ import annotations

import os
import re

_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
_CONTROL_PANEL = os.path.join(_ROOT, "iMakHQ", "control_panel.py")
_DUP_GUARD = os.path.join(_ROOT, "iMakHQ", "tools", "dup_guard.py")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_dup_guard_exposes_refresh_cache_mode():
    src = _read(_DUP_GUARD)
    assert '"--refresh-cache" in args' in src, \
        "cache だけを取り直すモードが無い (excluder の前に鮮度を作れない)"
    assert "ensure_fresh_live_cache()" in src


def test_control_panel_refreshes_cache_before_excluder():
    src = _read(_CONTROL_PANEL)
    i_refresh = src.find("--refresh-cache")
    # ★excluder の呼出は `--check-csv`。"dedupe.checker" だと **先に出てくる
    #   --write-keys-from-csv の呼出** (control_panel.py:345) を掴んでしまい、
    #   順序が正しくても落ちる (2026-08-09: 実コードは refresh:414 < excluder:434 で正しい)。
    i_excluder = src.find('"--check-csv"')
    assert i_refresh != -1, "control_panel が cache 鮮度確保を呼んでいない"
    assert i_excluder != -1
    assert i_refresh < i_excluder, (
        "cache 鮮度確保が excluder より後ろにある = excluder が判定不能で素通りする"
    )


def test_refresh_failure_is_surfaced_not_silent():
    """取り直せなかった時に「除外が効かない」と分かる形で出すこと (silent 禁止)。"""
    src = _read(_CONTROL_PANEL)
    m = re.search(r"--refresh-cache[\s\S]{0,1200}", src)
    assert m and "判定不能で skip" in m.group(0), \
        "cache 更新に失敗した時、除外が効かないことが走行ログに出ない"
