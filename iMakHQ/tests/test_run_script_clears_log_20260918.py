"""走行のたびにログ欄を空にする (2026-09-18 ユーザー要望)。

直前の走行だけをコピーして貼れるようにするため、`run_script` は走行開始時に
`clear_log()` を呼ぶ。押し忘れで前走行が混ざる実害 (2026-08-02: gshock の報告に
TCG の行が混入) の再発防止も兼ねる。
"""
import re
from pathlib import Path

PANEL = Path(__file__).resolve().parents[1] / "control_panel.py"


def _run_script_body() -> str:
    src = PANEL.read_text(encoding="utf-8")
    start = src.index("    def run_script(self, idx):")
    # 次の def (同じインデント) までを本体とみなす
    nxt = re.search(r"\n    def \w+\(", src[start + 10:])
    end = start + 10 + nxt.start() if nxt else len(src)
    return src[start:end]


def test_run_script_calls_clear_log():
    assert "self.clear_log()" in _run_script_body()


def test_clear_log_runs_before_the_header_line():
    body = _run_script_body()
    assert body.index("self.clear_log()") < body.index("▶ {script['label']}")


def test_log_frame_has_clear_button():
    """ログ枠の中にも「表示を消す」ボタンがある (2026-09-18 ユーザー要望)。

    状態ライン右端の「ログクリア」は見つけにくかった。
    """
    src = PANEL.read_text(encoding="utf-8")
    assert "表示を消す" in src
    assert 'text="🗑 表示を消す", command=self.clear_log' in src
