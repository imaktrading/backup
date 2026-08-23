"""取下げボタンが **前回分のスプシ後始末を先に**やる (2026-08-24 ユーザー指示)。

別ボタンを増やさず、押す順番を「掃除 → 次の CSV」で固定する。
やり忘れると B列に死んだ itemID が残り、仕入元が復活しても二度と出品されない
(実測: 8/23 の 361件 のうち 167件 が残っていた)。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import cull_end as C  # noqa: E402

SRC = os.path.join(os.path.dirname(__file__), "..", "tools", "cull_end.py")


def _src():
    return open(SRC, encoding="utf-8").read()


def test_main_runs_writeback_first():
    """★CSV を作る前に後始末を呼ぶ (順番が逆だと意味がない)."""
    src = _src()
    i_wb = src.find("writeback_previous()", src.find("def main("))
    i_sel = src.find("select(rows", src.find("def main("))
    assert i_wb > 0 and i_sel > 0
    assert i_wb < i_sel, "後始末が CSV 作成より後になっている"


def test_writeback_failure_does_not_stop_csv():
    """掃除が失敗しても CSV は出す (掃除は次回また拾えるが、CSV が出ないほうが困る)."""
    src = _src()
    i = src.find("def writeback_previous")
    body = src[i:src.find("def main(", i)]
    assert "except Exception" in body
    assert "次回また拾います" in body


def test_writeback_can_be_skipped():
    """`--no-writeback` で切れる (掃除だけ避けたい時のため)."""
    assert "--no-writeback" in _src()


def test_argv_is_restored():
    """後始末が sys.argv を書き換えるので、本処理の前に戻すこと
    (戻さないと --live 等の指定が消える)."""
    src = _src()
    i = src.find("def main(")
    body = src[i:i + 900]
    assert "argv = list(sys.argv)" in body
    assert "sys.argv = argv" in body


def test_writeback_is_reused_not_reimplemented():
    """後始末の中身は cull_writeback を呼ぶ (2箇所に同じ処理を書かない)."""
    src = _src()
    i = src.find("def writeback_previous")
    body = src[i:src.find("def main(", i)]
    assert "import cull_writeback" in body
    assert "CW.main()" in body
