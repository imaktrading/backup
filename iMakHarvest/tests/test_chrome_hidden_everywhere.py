"""tests/test_chrome_hidden_everywhere - 収集用 Chrome を画面に出さない.

2026-08-19 user 指摘「何回も言わさないでよ。毎回同じような処理をする場合、
画面に出さないようにできないの？」

- 非 headless は必須 (headless だと 1語15件 → 6件)
- 画面外へ飛ばすのは Windows が可視領域へ戻すので効かない (実測 L=-7)
- → ウィンドウごと隠す。**driver を起こす全箇所**で呼ぶ
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from scrapers import _chrome_util

pytestmark = pytest.mark.offline

ROOT = Path(__file__).resolve().parent.parent
# driver を起こしているファイル (grep で uc.Chrome( を持つ物)
DRIVER_FILES = sorted(
    p for p in list(ROOT.glob("scrapers/*.py")) + list(ROOT.glob("*.py"))
    if "uc.Chrome(" in p.read_text(encoding="utf-8")
)


def test_driver_files_are_discovered():
    assert len(DRIVER_FILES) >= 5, [p.name for p in DRIVER_FILES]


@pytest.mark.parametrize("path", DRIVER_FILES, ids=lambda p: p.name)
def test_every_driver_creation_hides_the_window(path):
    """uc.Chrome を起こしたら hide_browser_window を呼ぶ (呼び忘れ検出)."""
    src = path.read_text(encoding="utf-8")
    assert "hide_browser_window" in src, f"{path.name} で hide_browser_window を呼んでいない"


def test_onscreen_env_var_disables_hiding(monkeypatch):
    monkeypatch.setenv("IMAK_CHROME_ONSCREEN", "1")
    assert _chrome_util.onscreen_requested()
    monkeypatch.setenv("IMAK_CHROME_ONSCREEN", "")
    assert not _chrome_util.onscreen_requested()


def test_hide_is_noop_without_driver(monkeypatch):
    """driver が壊れていても例外を出さない (収集を止めない)."""
    monkeypatch.delenv("IMAK_CHROME_ONSCREEN", raising=False)

    class _Dead:
        def execute_script(self, *a, **k):
            raise RuntimeError("dead")

    assert _chrome_util.hide_browser_window(_Dead()) is False


def test_minimize_is_not_used_anywhere():
    """最小化は描画が止まって件数が落ちるので使わない."""
    for path in DRIVER_FILES:
        assert not re.search(r"minimize_window\s*\(", path.read_text(encoding="utf-8")), path.name
