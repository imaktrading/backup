# -*- coding: utf-8 -*-
"""RESTOCK照合で「仕入高(売れにくい)」を前段除外する判定の回帰テスト (2026-06-19)。

ユーザー要望: 仕入高は照合の段階で候補から外す(後段check_csvの二重価格除外を回避)。
_v8_label が「⚠仕入高...」を返す行のみ除外、市場内/判定不能/計算不可は照合に出す。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

import psa_resource_gate as gate


def test_high_cost_excluded():
    assert gate._is_high_cost("⚠仕入高:市場で売れにくい (利益には$502必要 > 市場$277 / 原価¥45000)") is True


def test_market_ok_not_excluded():
    assert gate._is_high_cost("✅市場内 (V8出品$401 ≤ 市場$450 / 原価¥39000)") is False


def test_unjudgeable_not_excluded():
    # cost/cur 無 → "" : 判定不能は照合に出す(fail-open=人が見る)
    assert gate._is_high_cost("") is False
    assert gate._is_high_cost(None) is False


def test_calc_error_not_excluded():
    assert gate._is_high_cost("V8計算不可(TypeError)") is False
