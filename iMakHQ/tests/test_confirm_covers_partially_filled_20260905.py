# -*- coding: utf-8 -*-
"""補が1本でもある出品が目視に出て来なかった件 (2026-09-05)。

同日に「既存と新規を見比べて安い順に最大5本 持つ」(rank_backurls) を入れたが、
③目視の対象が **補0本だけ** (max_backups=1) だったため、既存補は常に空 =
入れ替えが一度も起きない = **通り道が無い**状態だった。

実測 (2026-09-05 の商品管理シート):
    補0本   45件   ← ③に出ていたのはここだけ
    補≤1本  209件
    満杯未満 409件
= 364件が どのボタンにも出ないまま、高い仕入元を持ち続けていた。

対策: 目視の対象を満杯未満まで広げ、**補が少ない順**に出す (丸腰が先。丸腰が死ぬので)。
探す側 (夜間) は従来どおり 補0本 優先のまま。
"""
import os
import sys

_HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TOOLS = os.path.join(_HQ, "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import psa_hoju_fill as H  # noqa: E402

NCOL = 40


def _row(iid, cert="123456", aux=(), listed="2026-09-01", key="one_piece_tcg:OP01-001"):
    r = [""] * NCOL
    r[H.B] = iid
    r[H.CERT] = cert
    r[H.CATEGORY] = "TCG"
    r[H.KEY] = key
    r[H.LISTED_AT] = listed
    for i, u in enumerate(aux):
        r[H.AUX0 + i] = u
    return r


def _vals(rows):
    return [[f"c{i}" for i in range(NCOL)]] + rows


def test_thresholds_are_split_between_search_and_confirm():
    assert H.SEARCH_MAX_BACKUPS == 1          # 探す側は丸腰優先 (従来どおり)
    assert H.CONFIRM_MAX_BACKUPS == H.AUXN    # 目視は満杯未満すべて


def test_partially_filled_rows_reach_the_confirm_flow():
    """補1〜4本の出品が目視の対象に入る (今回の穴そのもの)。"""
    vals = _vals([
        _row("a", aux=()),                       # 補0
        _row("b", aux=("u1",)),                  # 補1
        _row("c", aux=("u1", "u2", "u3", "u4")),  # 補4
        _row("d", aux=("u1", "u2", "u3", "u4", "u5")),  # 満杯 = 対象外
    ])
    ids = [t["itemID"] for t in
           H.select_backfill_targets(vals, max_backups=H.CONFIRM_MAX_BACKUPS)]
    assert ids == ["a", "b", "c"], ids        # 満杯だけ外れる


def test_search_side_is_unchanged():
    """夜間の探す側は 補0本 だけのまま (振る舞いを変えていない)。"""
    vals = _vals([_row("a", aux=()), _row("b", aux=("u1",))])
    ids = [t["itemID"] for t in
           H.select_backfill_targets(vals, max_backups=H.SEARCH_MAX_BACKUPS)]
    assert ids == ["a"]


def test_fewest_backups_come_first():
    """丸腰から順に出す。補4本が丸腰より先に出たら、死ぬ方を後回しにしてしまう。"""
    vals = _vals([
        _row("full4", aux=("u1", "u2", "u3", "u4"), listed="2026-09-04"),
        _row("naked", aux=(), listed="2026-08-01"),
        _row("one", aux=("u1",), listed="2026-09-03"),
    ])
    ids = [t["itemID"] for t in H.select_backfill_targets(vals, max_backups=5)]
    assert ids == ["naked", "one", "full4"], ids


def test_newest_first_within_the_same_backup_count():
    """同じ本数の中では新規出品が先 (2026-07-28 の決定は残す)。"""
    vals = _vals([
        _row("old", aux=("u1",), listed="2026-08-01"),
        _row("new", aux=("u2",), listed="2026-09-04"),
    ])
    ids = [t["itemID"] for t in H.select_backfill_targets(vals, max_backups=5)]
    assert ids == ["new", "old"], ids


def test_panel_confirm_button_runs_15_items():
    """③目視は1回15件 (2026-09-05 ユーザー指示で 10→15)。"""
    src = open(os.path.join(_HQ, "control_panel.py"), encoding="utf-8").read()
    assert '"psa_hoju_fill.py", "confirm", "--limit=15"' in src
