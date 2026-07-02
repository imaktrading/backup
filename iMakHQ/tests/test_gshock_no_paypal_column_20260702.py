#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gshock_to_csv: PayPalAccepted 列を出さない + header↔build_row 整合 (2026-07-02)。

事故: gshock CSV の レガシー決済列 `PayPalAccepted=1` が、managed payments 完全移行後の
eBay File Exchange でビジネスポリシー無効の旧モードを誘発 → 送料プロファイル未適用 →
「有効な配送サービス無し(err 21915469)」で全8件失敗。列除去で Warning のみで出品成功を実機確認。
TCG generator は元々この列が無く無傷。

本テストは AST で (1)PayPalAccepted 列の非存在 (2)headers 数 == build_row return 数(整合)を固定。
列を1つ足し引きすると positional zip がズレて全列破綻するため、整合ガードは必須。
"""
import ast
import os

_GSHOCK = os.path.join(os.path.dirname(__file__), "..", "..", "iMakG-shock", "gshock_to_csv.py")


def _lists():
    tree = ast.parse(open(_GSHOCK, encoding="utf-8").read())
    ret_n = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "build_row":
            for s in ast.walk(node):
                if isinstance(s, ast.Return) and isinstance(s.value, ast.List):
                    ret_n = len(s.value.elts)
    hdr_vals = None
    hdr_n = None
    for node in ast.walk(tree):
        if isinstance(node, ast.List) and node.elts and isinstance(node.elts[0], ast.Constant):
            vals = [e.value for e in node.elts
                    if isinstance(e, ast.Constant) and isinstance(e.value, str)]
            if vals and str(vals[0]).startswith("*Action"):
                hdr_vals, hdr_n = vals, len(node.elts)
    return hdr_vals, hdr_n, ret_n


def test_no_paypal_accepted_column():
    hdr_vals, _, _ = _lists()
    assert hdr_vals is not None, "gshock header list を検出できず"
    assert "PayPalAccepted" not in hdr_vals, "PayPalAccepted 列が復活している(File Exchange 全弾きの根)"


def test_header_row_alignment():
    _, hdr_n, ret_n = _lists()
    assert hdr_n is not None and ret_n is not None
    assert hdr_n == ret_n, f"header数({hdr_n}) != build_row return数({ret_n}) = positional列ズレ"
