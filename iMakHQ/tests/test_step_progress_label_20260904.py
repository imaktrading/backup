# -*- coding: utf-8 -*-
"""①②③ のどこまで行ったかをボタンに出す (2026-09-04 ユーザー要望)。

> ①②③あるやつは、順番に押すと思うけど、どこまで行ったか分からなくなる
> ラベルは2段にしてね。1行並びだと見切れたりして、見づらいから

## 決めたこと
- 走行が終わったら **そのボタンの時刻を残す**。ラベルの2段目に「今日 07:11 済」
- まだ押していない **先頭** で、かつ仕事が在るものに「← 次」
- 日付が変われば自然に消える (today と比べるだけ。リセット処理を持たない)
- 2段目が空でも **2段のまま**にする (押すたびに高さが変わると読みにくい)
- 順番は STEP_FLOWS が唯一の定義。コードに「PSAなら〜」の分岐を書かない
"""
import ast
import io as _io
import os

_HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = _io.open(os.path.join(_HQ, "control_panel.py"), encoding="utf-8").read()


def _step_marks():
    """GUI を起動せず、純関数だけ取り出して動かす。"""
    tree = ast.parse(_SRC)
    cls = next(n for n in tree.body
               if isinstance(n, ast.ClassDef) and n.name == "ListingPanel")
    fn = next(n for n in cls.body
              if isinstance(n, ast.FunctionDef) and n.name == "step_marks")
    ns = {}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])),
                 "<x>", "exec"), ns)
    f = ns["step_marks"]
    return f.__func__ if hasattr(f, "__func__") else f


FLOW = (("psa_gate", "restock_build", "restock_wb"),)
LOG = {"psa_gate": "2026-09-04T05:56:00", "restock_build": "2026-09-04T07:11:33",
       "restock_wb": "2026-09-04T07:22:14"}


def test_shows_when_each_step_ran_today():
    got = _step_marks()(FLOW, LOG, {}, "2026-09-04")
    assert got["psa_gate"] == "今日 05:56 済"
    assert got["restock_wb"] == "今日 07:22 済"


def test_marks_the_first_unpressed_step_with_work():
    """①だけ押した状態なら ② に「← 次」。③には付けない (順番に1つだけ)。"""
    got = _step_marks()(FLOW, {"psa_gate": "2026-09-04T05:56:00"},
                        {"restock_build": True, "restock_wb": True}, "2026-09-04")
    assert got["restock_build"] == "← 次"
    assert got["restock_wb"] == ""


def test_no_work_means_no_next_mark():
    """仕事が0件なら「次」と言わない (押しても何も出ない物を勧めない)。"""
    assert _step_marks()(FLOW, {}, {}, "2026-09-04") == {
        "psa_gate": "", "restock_build": "", "restock_wb": ""}


def test_a_new_day_clears_it():
    """日付が変われば全部まっさら。リセット処理を持たない作り。"""
    got = _step_marks()(FLOW, LOG, {"psa_gate": True}, "2026-09-05")
    assert got["psa_gate"] == "← 次"
    assert got["restock_build"] == "" and got["restock_wb"] == ""


# ── 見た目の約束 ──────────────────────────────────────────
def test_label_is_always_two_lines():
    """2段目が空でも改行を入れる = 押すたびに高さが変わらない。"""
    i = _SRC.index("def paint_hoju_badge")
    body = _SRC[i:i + 1800]
    assert 'else f"{base}' + chr(92) + 'n"' in body, "空の時に2段目を作っていない"


def test_the_order_is_data_not_branches():
    """順番は表で持つ。コードに『PSAなら〜』を書かない (共通化の呪文②)。"""
    i = _SRC.index("STEP_FLOWS = (")
    seg = _SRC[i:i + 900]
    for b in ("psa_gate", "restock_build", "restock_wb", "ut_restore", "kuji_refresh"):
        assert b in seg, b


def test_the_time_is_recorded_when_a_run_finishes():
    """走行の完了時に記録する (押した瞬間ではない = 途中で落ちた分を済にしない)。"""
    i = _SRC.index("走行後に残件を数え直す")
    seg = _SRC[i:i + 700]
    assert "_remember_step_run" in seg
    assert seg.index("_remember_step_run") < seg.index("refresh_hoju_badge")
