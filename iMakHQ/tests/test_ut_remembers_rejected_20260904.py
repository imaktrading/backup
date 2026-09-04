# -*- coding: utf-8 -*-
"""UT: 一度「違う」と外した候補は二度と出さない (2026-09-04 ユーザー報告)。

> UT再仕入れ②だけど、前回見たものと同じのが出てくるけど

UT には PSA の「補URL候補NG」に当たる記録が無く、人が外しても
翌日 夜間バッチが同じ候補を拾い直して、また同じものが並んでいた。
人の1クリックを捨てない (PSA 側は 2026-07-30 に同じ手当てをしている)。

★補URL(②目視) と 再仕入れ(②目視) の **両方**に入れる。片方だけだと
  もう片方から同じ候補が戻ってくる (今日 何度も踏んだ形)。
"""
import io as _io
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_TOOLS = os.path.join(_ROOT, "iMakHQ", "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import ut_hoju_fill as U                                       # noqa: E402


def test_ledger_round_trip(tmp_path):
    p = str(tmp_path / "ng.json")
    assert U.load_cand_ng(p) == {}          # 無い時は空 (候補を消す方に倒さない)
    assert U.remember_cand_ng([("i1", "u1"), ("i1", "u2")], p) == 2
    assert U.remember_cand_ng([("i1", "u1")], p) == 0          # 同じものは増やさない
    assert U.load_cand_ng(p) == {"i1": ["u1", "u2"]}


def test_rejected_candidates_are_dropped():
    cands = [{"url": "u1"}, {"url": "u2"}, {"url": "u3"}]
    assert [c["url"] for c in U.drop_ng_candidates(cands, ["u2"])] == ["u1", "u3"]
    assert U.drop_ng_candidates(cands, ["u1", "u2", "u3"]) == []
    assert [c["url"] for c in U.drop_ng_candidates(cands, [])] == ["u1", "u2", "u3"]


def test_both_review_paths_record_and_filter():
    """補URL目視 と 再仕入れ目視 の両方に入っていること。"""
    s = _io.open(os.path.join(_TOOLS, "ut_hoju_fill.py"), encoding="utf-8").read()
    assert s.count("remember_cand_ng(_ng_new)") == 2, "片方の目視でしか記録していない"
    assert s.count("drop_ng_candidates(") >= 3, "片方の目視でしか除外していない"
    # 除外した結果を実際に画面へ渡していること (元の candidates を渡し直さない)
    assert s.count('"candidates": _cands})') == 2


def test_an_item_with_only_rejected_candidates_is_not_shown():
    """全部 外し済みなら、その出品ごと目視に出さない (空の画面を出さない)。"""
    s = _io.open(os.path.join(_TOOLS, "ut_hoju_fill.py"), encoding="utf-8").read()
    assert s.count("n_allng += 1") == 2
    assert "前に外した候補しか無い" in s
