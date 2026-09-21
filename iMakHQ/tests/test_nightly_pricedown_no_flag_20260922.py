"""夜の処理は値下げ印 (AL列) を書かない (2026-09-22)。

AL列はリバイスくんが毎朝読んで eBay の値段を下げる。9/3 から夜の処理が書いていたため、
ユーザーの判断を通らずに 334件が5%値下げされていた。夜は一覧だけ、印はボタンで書く。
"""
import os

BAT = os.path.join(os.path.dirname(__file__), "..", "tools", "run_hoju_search.bat")


def test_夜のpricedownは印を書かない設定で起動する():
    lines = [ln.strip() for ln in open(BAT, encoding="utf-8").read().splitlines()]
    i = next(n for n, ln in enumerate(lines) if ln.startswith("python -u noconvert_pricedown.py"))
    assert lines[i - 1] == "set NOCONVERT_NO_FLAG_WRITE=1"
    assert lines[i + 1] == "set NOCONVERT_NO_FLAG_WRITE="
