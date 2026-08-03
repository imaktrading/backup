# -*- coding: utf-8 -*-
"""完走後の要約は **run log ファイル** から読む (2026-08-03)。

実害 (2026-08-02 BRAVO 起票): 要約が `self.log.get('1.0','end')` = パネルのログ欄全文を
読んでいたため、**ログクリアを押し忘れると前走行の数字/cert が混ざる**。
gshock の走行報告に TCG の「入稿OK6件」「#155393557」が混入した。
さらにログ欄は 5000行を超えると先頭1000行が削除されるので、長い走行では頭が欠ける。

run log は走行ごとに新規ファイル (`📝 run log: <path>`) なので、押し忘れにもトリムにも
影響されない。読めない時だけログ欄にフォールバックする (報告が消えるより混ざる方がまし)。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ""))

import importlib.util

_CP = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "control_panel.py"))


class _FakeLog:
    """tkinter Text の最小 stub (get だけ)。"""

    def __init__(self, text):
        self._t = text

    def get(self, *_a):
        return self._t


class _Panel:
    """_run_log_text だけを取り出して検証するための最小ホスト。"""

    def __init__(self, path, widget_text):
        self._run_log_path = path
        self._run_log = None
        self.log = _FakeLog(widget_text)
        self.logged = []

    def append_log(self, msg):
        self.logged.append(msg)


def _bind():
    """control_panel を import せずに _run_log_text の実体だけ取り出す (tkinter 不要)。"""
    src = open(_CP, encoding="utf-8").read()
    start = src.index("    def _run_log_text(self):")
    end = src.index("    def _show_audit_summary(self", start)
    body = "\n".join(ln[4:] if ln.startswith("    ") else ln
                     for ln in src[start:end].split("\n"))
    ns = {}
    exec(compile(body, "_run_log_text", "exec"), ns)   # noqa: S102
    return ns["_run_log_text"]


_run_log_text = _bind()


def test_reads_the_run_log_file_not_the_widget(tmp_path):
    p = tmp_path / "run.log"
    p.write_text("=== 今回の走行 ===\n入稿OK 5件\n", encoding="utf-8")
    panel = _Panel(str(p), "前の走行の残骸: 入稿OK6件 #155393557")
    got = _run_log_text(panel)
    assert "今回の走行" in got
    assert "155393557" not in got, "ログ欄の前走行が混ざっている"


def test_falls_back_to_widget_when_no_path():
    panel = _Panel(None, "ログ欄の中身")
    assert _run_log_text(panel) == "ログ欄の中身"


def test_falls_back_when_file_missing(tmp_path):
    panel = _Panel(str(tmp_path / "no_such.log"), "ログ欄の中身")
    assert _run_log_text(panel) == "ログ欄の中身"
    assert any("読取失敗" in m for m in panel.logged), "フォールバックを黙ってやっている"


def test_falls_back_when_file_is_empty(tmp_path):
    """走行開始直後などで空なら、報告を空にせずログ欄で代用する。"""
    p = tmp_path / "run.log"
    p.write_text("   \n", encoding="utf-8")
    panel = _Panel(str(p), "ログ欄の中身")
    assert _run_log_text(panel) == "ログ欄の中身"
