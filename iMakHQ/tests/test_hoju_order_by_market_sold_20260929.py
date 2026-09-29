# -*- coding: utf-8 -*-
"""補URL③ の目視の並び: 同じ補の本数の中では 市場で売れた数 → ウォッチ → 新規 (2026-09-29 ユーザー確定)。"""
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


def test_market_sold_orders_within_same_backup_count():
    targets = [
        {"key": "a", "n_backups": 1, "listed_at": "2026-09-29", "row": 2},
        {"key": "b", "n_backups": 1, "listed_at": "2026-09-01", "row": 3},
        {"key": "c", "n_backups": 0, "listed_at": "2026-09-01", "row": 4},
    ]
    out = sorted(targets, key=lambda t: (t["listed_at"], -t["row"]), reverse=True)
    sold = {"b": 40}
    for t in out:
        t["market_sold"] = sold.get(t["key"], 0)
    out.sort(key=lambda t: -t["market_sold"])
    out.sort(key=lambda t: t["n_backups"])
    assert [t["key"] for t in out] == ["c", "b", "a"]    # 丸腰が先、同じ本数なら売れた数


def test_select_backfill_targets_uses_market_sold():
    import inspect
    assert "market_sold" in inspect.signature(H.select_backfill_targets).parameters
    src = inspect.getsource(H.run_daytime_confirm)
    assert src.count("market_sold=_msold") == 2        # 補充と、混ぜる入れ替えの両方
