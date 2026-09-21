"""★2026-09-22 確定した仕入元が売り切れの行は RESTOCK確定 から外して ① に戻す (永久に止まっていた14件)。"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
from psa_restock_build import split_dead_confirmed

H = ["itemID", "最安¥", "仕入URL", "RESTOCK状態", "確認済仕入URL"]


def test_dead_pending_row_is_dropped_others_kept():
    rows = [H,
            ["1", "100", "", "入稿待ち", "https://jp.mercari.com/item/m1?x=1"],   # 売り切れ → 外す
            ["2", "100", "", "入稿待ち", "https://jp.mercari.com/item/m9"],       # 新しい仕入元 → 残す
            ["3", "100", "", "実行済", "https://jp.mercari.com/item/m3"],         # 履歴 → 残す
            ["4", "100", "", "入稿待ち", "https://jp.mercari.com/item/m4"]]       # 売り切れ印なし → 残す
    sold = {"1": "https://jp.mercari.com/item/m1/", "2": "https://jp.mercari.com/item/m2",
            "3": "https://jp.mercari.com/item/m3"}
    keep, dropped = split_dead_confirmed(rows, sold)
    assert dropped == ["1"]
    assert [r[0] for r in keep] == ["itemID", "2", "3", "4"]


def test_nothing_sold_out_keeps_rows_as_is():
    rows = [H, ["1", "", "", "入稿待ち", "u"]]
    assert split_dead_confirmed(rows, {}) == (rows, [])
