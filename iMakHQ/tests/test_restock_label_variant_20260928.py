# -*- coding: utf-8 -*-
"""再仕入れ② が パラレルの KEY を「現物と別カード」と止めていた / 止めた行も「出した」と控えていた (2026-09-28)。

cert 151333415 (GD02-094 RARE+) と 154802375 (PRB02-010 ALTERNATE ART) が止まり、
③ を押しても「2件 → 2件」で減らなかった。
"""
import os

HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TCG = os.path.join(os.path.dirname(HQ), "iMakTCG")


def test_restock_trusts_sheet_key_that_matches_psa_label():
    s = open(os.path.join(TCG, "psa_restock_csv.py"), encoding="utf-8").read()
    i = s.index("forced_key_conflict(_forced, _bare, _berr)")
    assert "_PVG.pick(" in s[i:i + 2500]


def test_built_ledger_only_counts_rows_in_csv():
    s = open(os.path.join(HQ, "tools", "psa_restock_build.py"), encoding="utf-8").read()
    i = s.index("record_built(_built)")
    assert "_in_csv" in s[i - 1500:i]
