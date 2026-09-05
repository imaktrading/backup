# -*- coding: utf-8 -*-
"""夜間バッチの実績をパネルに出す (2026-09-04 ユーザー要望)。

> 夜間に探すのもやれているの？ラベルも更新されている？
> そやな。探せた件数と残数も

夜間バッチは **パネルを通らない** ので、ボタンの「今日 押した」には出ない。
代わりに `review_logs/hoju_search_cron_*.log` を読んで実績を出す。

★肝: 最後の段が `[end]` でない時は **「完走」と言わない**。
  途中で止まったのを成功と読ませない (fail-closed)。
"""
import ast
import io as _io
import os
import re

_HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = _io.open(os.path.join(_HQ, "control_panel.py"), encoding="utf-8").read()


def _fn():
    t = ast.parse(_SRC)
    f = next(n for n in t.body
             if isinstance(n, ast.FunctionDef) and n.name == "nightly_last_run")
    ns = {"os": os, "re": re, "WORKSPACE": r"c:/dev/iMak"}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[f], type_ignores=[])),
                 "<x>", "exec"), ns)
    return ns["nightly_last_run"]


def _log(tmp_path, steps, name="hoju_search_cron_2026-09-03.log"):
    p = tmp_path / name
    p.write_text(chr(10).join("[%s] 2026/09/03 %s " % (s, t) for s, t in steps),
                 encoding="utf-8")
    return str(tmp_path)


def test_finished_run_is_reported_with_times(tmp_path):
    d = _log(tmp_path, [("start", "23:30:03.38"), ("keyfill", "23:30:03.38"),
                        ("end", " 1:46:15.36")])
    got = _fn()(log_dir=d)
    assert got["done"] is True
    assert got["steps"] == 3 and got["date"] == "2026-09-03"


def test_a_stopped_run_is_not_called_finished(tmp_path):
    """★途中で止まったのを『完走』と言わない。最後の段を出して気づけるようにする。"""
    d = _log(tmp_path, [("start", "23:30:03.38"), ("topup", "00:04:52.91")])
    got = _fn()(log_dir=d)
    assert got["done"] is False
    assert got["last_step"] == "topup" and got["end"] == ""


def test_missing_log_is_said_plainly(tmp_path):
    got = _fn()(log_dir=str(tmp_path))
    assert got["error"] and got["done"] is False


def test_empty_log_is_not_a_success(tmp_path):
    p = tmp_path / "hoju_search_cron_2026-09-03.log"
    p.write_text("何も段が無い", encoding="utf-8")
    got = _fn()(log_dir=str(tmp_path))
    assert got["done"] is False and got["error"]


def test_the_panel_shows_it_on_the_status_button():
    """見るだけのボタン (補URL件数感) に出す。押す判断には使わないので色は変えない。"""
    i = _SRC.index('hs_txt = "')
    seg = _SRC[i:i + 1400]
    assert "nightly_last_run()" in seg
    # ★2026-09-06: 「探せた」は暦日でなく **その夜の日付** で数えるようになった。
    #   夜間は23:30開始なので、暦日で数えると朝は必ず0件だった (実測 128件 → 0件表示)。
    assert "その夜に探せた" in seg and "今夜また探す" in seg
    assert "途中で止まっています" in seg
