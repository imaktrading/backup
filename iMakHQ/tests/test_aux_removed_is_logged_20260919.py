"""補URL が **減った** ことも台帳に残ること (2026-09-19)。

台帳は「書いた値」しか残していなかったので、減ったこと自体が記録に出なかった。
実害: itemID 820041238874 が 9/16 に3本 → 9/19 に1本。経緯を誰も辿れなかった。
"""
import os
import sys

TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
sys.path.insert(0, TOOLS)
import aux_url_log as A


def test_消えたURLを記録する():
    got = A.build_removed({7: ["a", "b", "c"]}, {7: ["b"]}, "テスト")
    assert [r["url"] for r in got] == ["a", "c"]
    assert all(r["kind"] == "removed" for r in got)


def test_減っていなければ何も出さない():
    assert A.build_removed({7: ["a"]}, {7: ["a", "b"]}, "テスト") == []


def test_書込前の値を読んでから書く():
    """読まずに書くと『減った』が記録に出ない。"""
    src = open(os.path.join(TOOLS, "sheet_io.py"), encoding="utf-8").read()
    body = src.split("def write_aux_urls(")[1].split("\ndef ")[0]
    assert "before" in body and "get_all_values" in body
    assert body.index("before[row]") < body.index("ws.batch_update(reqs")   # 書く前に読む
    assert "record_removed" in body
