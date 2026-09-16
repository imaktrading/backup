# -*- coding: utf-8 -*-
"""RESTOCK: シートの KEY (forced) と現物からの解決が別カードなら出さない (2026-09-16)。

実害 (2026-09-15): cert 163004996 (SPECIAL ALTERNATE ART) がシート KEY `ST26-005_OP15`
(通常版 SR) の値で CSV に出た。現物からの解決は `ST26-005_p1` (Special / Alternative Art)。
依頼書: hq/requests/2026-09-15_act_code_proposals_tcg.md 提案①
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_ROOT, "iMakTCG"))

import tcg_new_gen_override as O  # noqa: E402


def test_different_card_is_conflict():
    bare = {"_card_id": "ST26-005_p1"}
    assert O.forced_key_conflict("one_piece_tcg:ST26-005_OP15", bare, None) == "ST26-005_p1"


def test_same_card_is_not_conflict():
    bare = {"_card_id": "ST26-005_p1"}
    assert O.forced_key_conflict("one_piece_tcg:ST26-005_p1", bare, None) == ""
    assert O.forced_key_conflict("ST26-005_p1", bare, None) == ""


def test_bare_unresolved_keeps_forced():
    """現物から決まらない時こそ人の確定 KEY を使う (見送りにしない)。"""
    assert O.forced_key_conflict("one_piece_tcg:X_p1", {}, "catalog 解決不能") == ""
    assert O.forced_key_conflict("one_piece_tcg:X_p1", {"_card_id": ""}, None) == ""
    assert O.forced_key_conflict("", {"_card_id": "X_p1"}, None) == ""


def test_restock_skip_line_is_counted_by_auditor():
    """見送り行が監査くんの「繰り返し見送り」の正規表現に載る形式であること。"""
    src = open(os.path.join(_ROOT, "iMakTCG", "psa_restock_csv.py"), encoding="utf-8").read()
    assert "forced_key_conflict(" in src
    sys.path.insert(0, os.path.join(_ROOT, "iMakHQ", "tools"))
    import csv_auditor
    line = ("    ⚠️ cert 163004996: シートの KEY=one_piece_tcg:ST26-005_OP15 と現物からの解決="
            "ST26-005_p1 が別カード → 出さない (商品管理シートの KEY 列を確認) (build skip)")
    assert csv_auditor._DROP_CERT_RE.search(line).group(1) == "163004996"
