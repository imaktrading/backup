# -*- coding: utf-8 -*-
"""種→出品行の目視に「番号が読めない」を足す (2026-09-09 ユーザー指示)。

    「カード番号読みとれずを追加して、対応終了にしてほしい。隠している人がいるからね」

証明番号を写真に写さない出品者がいる。番号を打てない → 印が付かない →
**同じ候補が毎回 目視に出続ける**。人が「読めない」と判断したらそこで終わりにする。
★推測で番号を入れてはいけない (証明番号は現物ごとに違う = 別の現物の番号になる)。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "tools"))
import newcand_confirm as N     # noqa: E402


def _item(i, price="1000"):
    return {"i": i, "url": f"https://jp.mercari.com/item/m{i}", "title": f"PSA10 テスト{i}",
            "key": "", "pid": "", "price": price}


def test_画面に番号が読めないの選択肢がある():
    html = N.build_cert_html([_item(0)]).decode("utf-8")
    assert "class='nonum'" in html
    assert "番号が読めない" in html
    # 押した時に送られること (JS が nonum を集めて POST する)
    assert "nonum.push(i)" in html
    assert "nonum:nonum" in html


def test_受け取り側がnonumを拾う():
    got = N.parse_cert_result({"certs": [{"i": 1, "cert": "12345678"}],
                               "sold": [2], "nonum": [3, "4", "x"]})
    assert got["certs"] == {1: "12345678"}
    assert got["sold"] == {2}
    assert got["nonum"] == {3, 4}          # 数字にならないものは捨てる


def test_nonumが無い古い形でも壊れない():
    got = N.parse_cert_result({"certs": [], "sold": []})
    assert got["nonum"] == set()


def test_印は自動同期で消えない():
    """人が押した結論を次の同期が消すと、同じ候補が永久に出続ける。"""
    assert N.DONE_MARK_NONUM not in N.AUTO_MARKS
    assert N.DONE_MARK_SOLD not in N.AUTO_MARKS


def test_印が付いた行は次から出ない():
    """pending_list_rows は 結論(印)のある行を出さない。"""
    rows = [list(N.OUT_HEADER)]
    for mark in ("", N.DONE_MARK_NONUM, N.DONE_MARK_SOLD):
        r = [""] * len(N.OUT_HEADER)
        r[0], r[N.OUT_DONE_COL] = N.USE_LIST, mark
        r[N.OUT_URL_COL] = "https://jp.mercari.com/item/m%s" % (mark or "none")
        rows.append(r)
    left = N.pending_list_rows(rows[1:])
    urls = [r[N.OUT_URL_COL] for r in left] if left and isinstance(left[0], list) else left
    assert len(left) == 1, f"印のある行まで残っている: {left}"
    assert "mnone" in str(urls)
