# -*- coding: utf-8 -*-
"""新規の並べ順が読む一覧 (トレジャーハント / 市場で売れた枚数) を KAGOYA に送る (2026-10-08)。

送っていなかったため KAGOYA では無い扱いになり、10/05 から「トレジャーハント 0件」で優先されていなかった。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
sys.path.insert(0, os.path.join(HERE, "..", "..", "iMakTCG"))


def _norm(p):
    return os.path.normcase(os.path.normpath(p))


def test_demand_lists_are_pushed_to_kagoya():
    import kagoya_button as KB
    import tcg_batch_select as TB
    pushed = {_norm(p) for p in KB.PUSH_EXTRA}
    assert _norm(TB.TREASURE_CSV) in pushed
    assert _norm(TB.MARKET_SOLD_CSV) in pushed


def test_missing_list_is_logged(tmp_path, capsys):
    import tcg_batch_select as TB
    assert TB.load_treasure_ids(str(tmp_path / "none.csv")) == set()
    assert TB.load_market_sold(str(tmp_path / "none.csv")) == {}
    out = capsys.readouterr().out
    assert "トレジャーハントの一覧がありません" in out
    assert "市場で売れた枚数の一覧がありません" in out
