# -*- coding: utf-8 -*-
"""補URL③ の目視の並び: 市場で売れた数 → ウォッチ → 補が少ない順 → 新規 (2026-09-29 ユーザー確定)。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import market_ledger as ML  # noqa: E402
import psa_hoju_fill as H  # noqa: E402


def test_sold_by_key_matches_dash_and_slash_forms():
    agg = {"SV2A-151": {"sold": 5, "title": "x"},
           "230/193": {"sold": 7, "title": "Pokemon M2a 230/193 PSA10"},
           "074/100": {"sold": 9, "title": "Anything with P in it PSA10"}}
    got = ML.sold_by_key(["pokemon_tcg:SV2a-151", "pokemon_tcg:M2a-230", "one_piece_tcg:P-074",
                          "pokemon_tcg:S12a-001"], agg)
    assert got == {"pokemon_tcg:SV2a-151": 5, "pokemon_tcg:M2a-230": 7}   # 1文字の弾コードは番号/総数で当てない


def test_order_is_sold_then_watch_then_backups_then_new():
    # 渡す時点で新規優先 (a が一番新しい)
    out = [{"key": "a", "itemID": "1", "n_backups": 0},
           {"key": "b", "itemID": "2", "n_backups": 3},
           {"key": "c", "itemID": "3", "n_backups": 0},
           {"key": "d", "itemID": "4", "n_backups": 2}]
    got = H.order_targets(out, 0, watch={"4": 5}, market_sold={"b": 40})
    # 売れた b が予備3本でも先頭 → ウォッチの d → 残りは予備が少ない順 (同数は新規優先で a, c)
    assert [t["key"] for t in got] == ["b", "d", "a", "c"]


def test_select_backfill_targets_uses_market_sold():
    import inspect
    assert "market_sold" in inspect.signature(H.select_backfill_targets).parameters
    src = inspect.getsource(H.run_daytime_confirm)
    assert src.count("market_sold=_msold") == 2        # 補充と、混ぜる入れ替えの両方
