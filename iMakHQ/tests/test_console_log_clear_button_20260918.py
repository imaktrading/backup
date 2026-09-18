"""新 Console のログに「表示を消す」ボタンがある (2026-09-18 ユーザー要望)。

直前の走行だけをコピーして貼りたい、が用途。旧パネル (control_panel.py) 側にも
同じボタンを置いてあるが、実際に動いているのは Console なので両方に要る。
"""
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "console" / "static"


def test_html_has_clear_button():
    s = (STATIC / "index.html").read_text(encoding="utf-8")
    assert 'id="drawer-clear"' in s
    assert "表示を消す" in s


def test_js_clears_the_log_box():
    s = (STATIC / "app.js").read_text(encoding="utf-8")
    assert '$("drawer-clear").addEventListener' in s
    assert '$("log").innerHTML = ""' in s


def test_clear_also_wipes_the_heading():
    """見出し (「失敗: … (returncode=1)」) も消す。

    2026-09-18 ユーザー指摘: ログ本文は消えたが見出しが残り「消えていない」に見えた。
    """
    s = (STATIC / "app.js").read_text(encoding="utf-8")
    i = s.index('$("drawer-clear").addEventListener')
    body = s[i:i + 700]
    assert '$("job-label").textContent = ""' in body
    assert '$("job-meta").textContent = ""' in body
