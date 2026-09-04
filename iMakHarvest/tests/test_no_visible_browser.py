"""tests/test_no_visible_browser - **ユーザーの画面を邪魔しない** ことをコードで守る.

2026-08-22 user 確定: 「言われなくても、常にそういう気配りを徹底して」。

実害:
  - 2026-08-18 収集中の Chrome が数時間 画面に出続けた
  - 2026-08-22 隠したはずのウィンドウが `maximize_window()` + `window.focus()` で
    また前面に出ていた (メルカリ検索)

守り方: **前面化する所は、直後に隠し直す**。 手動 click を待つ画面だけ例外
(user が操作するので表示が要る)。 例外は `wait_for_manual_load` / `manual` の分岐に
書くこと。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.offline

ROOT = Path(__file__).resolve().parents[1]
FOREGROUND_RE = re.compile(r"maximize_window\(\)|window\.focus\(\)")
LOOKAHEAD_LINES = 25


def _sources():
    for p in sorted((ROOT / "scrapers").glob("*.py")):
        yield p
    for p in sorted(ROOT.glob("run_harvest_*.py")):
        yield p


def test_every_foreground_call_hides_the_window_again():
    """前面化した後に hide_browser_window が無い所を落とす."""
    offenders = []
    for path in _sources():
        lines = path.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines):
            if not FOREGROUND_RE.search(line):
                continue
            window = "\n".join(lines[i:i + LOOKAHEAD_LINES])
            if "hide_browser_window" in window:
                continue
            if "wait_for_manual_load" in window or "manual" in window:
                continue      # 手動 click 待ちは表示が要る
            offenders.append(f"{path.name}:{i + 1}")
    assert not offenders, (
        "前面化したまま隠していない箇所がある (ユーザーの画面を邪魔する): "
        + ", ".join(offenders))


def test_hide_helper_exists_and_is_opt_outable():
    """デバッグ時だけ画面に出せること (IMAK_CHROME_ONSCREEN=1)."""
    from scrapers._chrome_util import hide_browser_window, onscreen_requested
    assert callable(hide_browser_window) and callable(onscreen_requested)
