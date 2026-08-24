"""落とした itemID を憶えて、次から候補に出さない (2026-08-24)。

これが無いと、静的な funnel CSV の上位を「済み」が占領し続け、毎回ほぼ空振りする。
実測: 200件選んで 158件が済み、実際に進んだのは 37件。
憶えれば **レポートを取り直さなくても、押すたびに次の200件** が出る。
itemID は一度終了したら二度と復活しないので、永久に外してよい。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import cull_end as C  # noqa: E402

import datetime
_OLD = datetime.date(2030, 1, 15)


def _row(i, age=100, price=200.0):
    return {"item_id": i, "flags": "CULL", "age_days": str(age), "price": str(price),
            "title": "t"}


def test_done_ids_are_excluded():
    """★済みは候補に出ない."""
    rows = [_row("a"), _row("b"), _row("c")]
    _c, eligible, _p = C.select(rows, done_ids={"b"}, today=_OLD)
    assert [r["item_id"] for r in eligible] == ["a", "c"]


def test_next_press_gets_the_next_batch():
    """★1回目の200件を憶えると、2回目は次の200件になる (レポート再取得なしで進む)."""
    rows = [_row(str(i), age=500 - i) for i in range(30)]
    _c, _e, first = C.select(rows, cap=10, today=_OLD)
    done = {r["item_id"] for r in first}
    _c, _e, second = C.select(rows, cap=10, done_ids=done, today=_OLD)
    assert len(second) == 10
    assert not (set(r["item_id"] for r in second) & done), "同じものが再び出ている"


def test_no_done_list_behaves_as_before():
    rows = [_row("a"), _row("b")]
    _c, eligible, _p = C.select(rows, today=_OLD)
    assert len(eligible) == 2


def test_load_done_missing_file_is_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "DONE_FILE", str(tmp_path / "nope.txt"))
    assert C.load_done() == set()


def test_remember_then_load(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "DONE_FILE", str(tmp_path / "done.txt"))
    C.remember_done(["1", "2"])
    C.remember_done(["3"])
    assert C.load_done() == {"1", "2", "3"}


def test_remember_ignores_blanks(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "DONE_FILE", str(tmp_path / "done.txt"))
    C.remember_done(["", "  ", "9"])
    assert C.load_done() == {"9"}


def test_main_remembers_only_successful_sends():
    """失敗した分を憶えると二度と拾えなくなる。成功分だけ記録すること."""
    src = open(os.path.join(os.path.dirname(__file__), "..", "tools", "cull_end.py"),
               encoding="utf-8").read()
    assert "remember_done(ok_ids)" in src
    assert "remember_done(picked" not in src
