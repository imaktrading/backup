# -*- coding: utf-8 -*-
"""補URLが「安い順の最大5本」にならず、埋まった枠に安い供給が入らなかった件 (2026-09-05)。

ユーザー指摘:
    「補URLを選ぶHTMLで、既に補が数件埋まっていて、今回8件補候補が出た。
      せっかく見つけた訳だから、全ての補と見比べて、最安を最大5件持つべきでは？」

従来 (compute_backurl_additions) は **既存を必ず残して空き枠だけ**埋めていたので、
補が5本埋まっている出品には、その日 目視で確認した もっと安い供給が1本も入らなかった。
補URLは「売れた時にどこから買うか」なので、安い順に持つ方が利益が出る。

値段が分かるのは「今日の候補に出ているURL」だけ。値段の分からない既存は
**押し出す根拠が無いので残す** (判定不能を破壊側に倒さない)。
"""
import os
import sys

_TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import psa_hoju_fill as H  # noqa: E402

U = "https://jp.mercari.com/item/m%d"


def _u(n):
    return U % n


def test_cheaper_new_url_replaces_pricier_existing_when_full():
    """5本埋まっていても、もっと安いのが確定したら入れ替わる (今回の要望そのもの)."""
    existing = [_u(1), _u(2), _u(3), _u(4), _u(5)]
    prices = {_u(i): 10000 + i * 100 for i in range(1, 6)}
    prices[_u(9)] = 5000                                   # 今日見つけた最安
    full, added, removed = H.rank_backurls(existing, [_u(9)], prices, max_slots=5)
    assert full[0] == _u(9), full
    assert added == [_u(9)]
    assert removed == [_u(5)], removed                     # 一番高い既存が押し出される
    assert len(full) == 5


def test_result_is_sorted_cheapest_first():
    existing = [_u(1)]
    prices = {_u(1): 9000, _u(2): 3000, _u(3): 6000}
    full, _added, _rm = H.rank_backurls(existing, [_u(2), _u(3)], prices, max_slots=5)
    assert full == [_u(2), _u(3), _u(1)]


def test_unknown_price_existing_is_kept():
    """値段が分からない既存は消さない。押し出す根拠が無い。"""
    existing = [_u(1)]
    full, _added, removed = H.rank_backurls(existing, [_u(2)], {_u(2): 4000}, max_slots=5)
    assert removed == []
    assert set(full) == {_u(1), _u(2)}
    assert full[0] == _u(2)                                # 値段が分かる方が先


def test_unknown_price_is_pushed_out_only_by_a_full_cheaper_set():
    """値段の分かる安いのが枠数そろった時だけ、値段不明の既存が落ちる。"""
    existing = [_u(1)]
    new = [_u(2), _u(3), _u(4), _u(5), _u(6)]
    prices = {u: 1000 for u in new}
    full, _added, removed = H.rank_backurls(existing, new, prices, max_slots=5)
    assert removed == [_u(1)]
    assert len(full) == 5


def test_no_duplicates_and_blank_ignored():
    full, added, removed = H.rank_backurls(["", _u(1), _u(1)], [_u(1), "  ", _u(2)],
                                           {_u(2): 100}, max_slots=5)
    assert full == [_u(2), _u(1)]
    assert added == [_u(2)] and removed == []


def test_nothing_new_keeps_existing_order():
    existing = [_u(1), _u(2)]
    full, added, removed = H.rank_backurls(existing, [], {}, max_slots=5)
    assert full == existing and added == [] and removed == []


def test_plan_writes_when_only_the_order_changed():
    """並べ替えただけでも書く (安い順に持ち直すのが目的)。"""
    NCOL = 40
    row = [""] * NCOL
    row[0] = _u(1)                       # A列 主URL
    row[1] = "111"                       # B列 itemID
    row[H.AUX0] = _u(7)                  # 既存補 (高い)
    vals = [[f"c{i}" for i in range(NCOL)], row]
    prices = {0: {_u(7): 9000, _u(8): 2000}}
    wb, added, dropped, replaced = H.plan_aux_writeback(
        {0: [_u(8)]}, [{"row": 2, "itemID": "111"}], vals, {}, guard_ok=True,
        price_by_url=prices)
    assert wb[2][:2] == [_u(8), _u(7)], wb
    assert added == 1 and dropped == [] and replaced == []
