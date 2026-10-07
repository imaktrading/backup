"""Q列「補充保留」の出品は 売れた分の補充・PSA 再仕入れ・補URL が触らない (2026-10-07 ユーザー: リピーターの注文中のミュウ)。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import psa_hoju_fill as H  # noqa: E402
import sheet_io as S  # noqa: E402


def test_hold_mark():
    r = [""] * 40
    assert not S.is_restock_hold(r)
    r[S.PRODUCT_COL_FLG] = "補充保留 10/7 リピーター注文中"
    assert S.is_restock_hold(r)


def test_hoju_skips_held_rows():
    r = [""] * 40
    r[H.B], r[H.CERT], r[H.CATEGORY] = "820206076676", "162885050", "TCG"
    r[0] = "https://jp.mercari.com/item/m1"
    assert len(H.select_backfill_targets([["hdr"], list(r)], max_backups=5)) == 1
    r[S.PRODUCT_COL_FLG] = "補充保留"
    assert H.select_backfill_targets([["hdr"], r], max_backups=5) == []


def test_restock_paths_read_the_mark():
    here = os.path.join(os.path.dirname(__file__), "..", "tools")
    for f in ("sold_restock.py", "psa_resource_gate.py"):
        assert "is_restock_hold" in open(os.path.join(here, f), encoding="utf-8").read(), f
