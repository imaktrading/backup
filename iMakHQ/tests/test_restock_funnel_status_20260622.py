#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PSA再仕入れ funnel 出品状態ラベルの判定 (2026-06-22)。

手動スナップショットだと 🔄書戻しで実行済になっても funnel に反映されない問題への対応で、
出品状態を RESTOCK確定 join でフロー内自動更新する(🃏 gate / 🔄 writeback 両方で呼ぶ)。
本テストは状態判定の純関数を固定。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
from restock_funnel_status import compute_status  # noqa: E402

CONF = {
    "111": "実行済(qty復活)",
    "222": "入稿待ち(qty=0)",
    "333": "確定",
}
EXCL = {"999"}


def test_excluded_wins():
    assert compute_status("999", CONF, EXCL, "再仕入れ可◎") == "✕対象外"


def test_done():
    assert compute_status("111", CONF, EXCL, "再仕入れ可◎") == "✅再出品済"


def test_pending_upload():
    assert compute_status("222", CONF, EXCL, "再仕入れ可◎") == "⏳入稿待ち(CSV→UL)"


def test_confirmed_other():
    assert compute_status("333", CONF, EXCL, "再仕入れ可◎") == "確定"


def test_resourceable_not_yet_confirmed():
    """確定タブに無く 可◎ = 視覚確証待ち。"""
    assert compute_status("444", CONF, EXCL, "再仕入れ可◎") == "🔍確証待ち(🃏)"


def test_end_candidate():
    """確定タブに無く 不能✕ = End候補。"""
    assert compute_status("555", CONF, EXCL, "不能✕(End候補)") == "—(End候補)"


def test_empty_itemid_falls_to_kahi():
    """itemID 空でも 可否で分類(confirmed/excluded には入れない)。"""
    assert compute_status("", CONF, EXCL, "再仕入れ可◎") == "🔍確証待ち(🃏)"
    assert compute_status("", CONF, EXCL, "不能✕(End候補)") == "—(End候補)"
