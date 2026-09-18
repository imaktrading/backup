"""ログは「直前の1本だけ」を扱う (2026-09-18 ユーザー要望)。

コピーすると走行が3本ぶん入ってしまい、貼って相談する時に使えなかった。
走行の始まりは「▶ 」で始まる行なので、そこを境にする。
- 「🗑 ログを消す」= 最後の「▶ 」より前を消す (1本しか無ければ全部消す)
- 「ログをコピー」= 最後の「▶ 」から下だけをコピーする
"""
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "console" / "static"


def _js() -> str:
    return (STATIC / "app.js").read_text(encoding="utf-8")


def test_html_has_clear_button():
    s = (STATIC / "index.html").read_text(encoding="utf-8")
    assert 'id="drawer-clear"' in s
    assert "ログを消す" in s


def test_run_boundary_is_the_marker_line():
    # ▶ = ▶ (走行の始まり)
    assert "function lastRunStart()" in _js()
    assert "\u25b6" in _js()


def test_clear_removes_only_the_earlier_runs():
    s = _js()
    i = s.index('$("drawer-clear").addEventListener')
    body = s[i:i + 1200]
    assert "lastRunStart()" in body
    assert "removeChild" in body
    assert '$("log").innerHTML = ""' in body          # 1本しか無い時は全部消す


def test_clear_also_wipes_the_heading():
    s = _js()
    i = s.index('$("drawer-clear").addEventListener')
    body = s[i:i + 1200]
    assert '$("job-label").textContent = ""' in body
    assert '$("job-meta").textContent = ""' in body


def test_copy_takes_only_the_last_run():
    s = _js()
    i = s.index('$("drawer-copy").addEventListener')
    body = s[i:i + 800]
    assert "lastRunText()" in body
    assert '$("log").innerText' not in body           # 全文コピーに戻っていないこと
