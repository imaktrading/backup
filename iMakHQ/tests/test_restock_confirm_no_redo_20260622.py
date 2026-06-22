#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RESTOCK視覚確証: 確定済を再表示しない + 上書きで既存を消さない (2026-06-22)。

ユーザー要望: RESTOCK視覚確証で同じ11件(うち再出品済6)が毎回出て同じ確証作業の繰り返しが面倒。
+ 発覚した上書きバグ: _run_restock_confirm が RESTOCK確定タブを毎回 replace で書くため、新規5件だけ
確証すると既存12件(実行済)が消える。
対策: ① 既にRESTOCK確定済の itemID は視覚確証に出さない ② 書込は既存+新規のマージ。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
# psa_resource_gate は重い import 群を持つので、純関数だけ取り出してテスト
import importlib.util
_P = os.path.join(os.path.dirname(__file__), "..", "tools", "psa_resource_gate.py")
_spec = importlib.util.spec_from_file_location("psa_resource_gate", _P)
# 依存の重い import を避けるため、関数定義だけ読む手段が無いので通常 import を試みる
try:
    g = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(g)
    _LOADED = True
except Exception:
    _LOADED = False

import pytest

pytestmark = pytest.mark.skipif(not _LOADED, reason="psa_resource_gate import 不可環境")

HEADER = ["itemID", "card_no", "title", "最安チャネル", "最安¥", "eBay現$", "V8判定",
          "確認済仕入URL", "ebay_url", "確証日"]


def test_confirmed_iids_extracts_existing():
    existing = [HEADER,
                ["111", "OP09-062", "t", "", "", "", "", "", "", "2026-06-20"],
                ["222", "OP07-051", "t", "", "", "", "", "", "", "2026-06-20"]]
    assert g._restock_confirmed_iids(existing) == {"111", "222"}


def test_confirmed_iids_empty():
    assert g._restock_confirmed_iids([]) == set()
    assert g._restock_confirmed_iids([HEADER]) == set()


def test_merge_keeps_existing_and_adds_new():
    """既存12件相当を維持しつつ新規を追加(上書きで消えない)。"""
    existing = [HEADER + ["RESTOCK状態", "状態確認日"],
                ["111", "A", "t", "", "", "", "", "", "", "2026-06-20", "実行済(qty復活)", "2026-06-20"]]
    new = [["999", "B", "t2", "", "", "", "", "", "", "2026-06-22"]]
    out = g._merge_restock_out(existing, new, HEADER)
    iids = [r[0] for r in out[1:]]
    assert "111" in iids, "既存(実行済)が消えていない"
    assert "999" in iids, "新規が追加されている"
    assert out[0] == existing[0], "既存ヘッダ(状態列含む)を維持"


def test_merge_new_overrides_duplicate():
    """同 itemID は新規優先(重複しない)。"""
    existing = [HEADER, ["111", "A", "old", "", "", "", "", "", "", "2026-06-20"]]
    new = [["111", "A", "new", "", "", "", "", "", "", "2026-06-22"]]
    out = g._merge_restock_out(existing, new, HEADER)
    rows = [r for r in out[1:] if r[0] == "111"]
    assert len(rows) == 1, "itemID重複しない"
    assert rows[0][2] == "new", "新規が優先"


def test_merge_empty_existing_uses_default_header():
    out = g._merge_restock_out([], [["111", "A", "t", "", "", "", "", "", "", "2026-06-22"]], HEADER)
    assert out[0] == HEADER
    assert out[1][0] == "111"
