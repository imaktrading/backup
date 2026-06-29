# -*- coding: utf-8 -*-
"""PSA CSV から Age Level (C:Age Level / "6+") を完全除去した回帰テスト (2026-06-29 CPSC対応)。

依頼: 2026-06-29_psa_age_level_remove.md
- PSA鑑定品=コレクター市場=非児童製品。PSA公式店も Age Level 未設定が業界標準。
- "6+" = 児童製品扱い → 7/8 CPSC eFiling 通関リスク。列ごと出力停止。

検証 (API不要・AST 静的解析):
  1. header list に "C:Age Level" が無い
  2. build_row の return list に "6+" 定数が無い
  3. header 要素数 == build_row return 要素数 (列ズレ=出品破壊 を防ぐ最重要不変条件)
本体 psa_to_csv.py と fork psa_restock_csv.py の両方を検証。
"""
import ast
import os

_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
_FILES = [
    os.path.join(_ROOT, "iMakTCG", "psa_to_csv.py"),
    os.path.join(_ROOT, "iMakTCG", "psa_restock_csv.py"),
]


def _parse(path):
    with open(path, encoding="utf-8") as f:
        return ast.parse(f.read())


def _header_list(tree):
    """"*Action..." を含む list literal (= CSV header) を返す。"""
    for node in ast.walk(tree):
        if isinstance(node, ast.List):
            consts = [e.value for e in node.elts
                      if isinstance(e, ast.Constant) and isinstance(e.value, str)]
            if any(s.startswith("*Action(SiteID") for s in consts):
                return node
    return None


def _build_row_return(tree):
    """build_row 内の最長 return list (= 1行分の値) を返す。"""
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "build_row":
            returns = [n.value for n in ast.walk(node)
                       if isinstance(n, ast.Return) and isinstance(n.value, ast.List)]
            return max(returns, key=lambda L: len(L.elts)) if returns else None
    return None


def _consts(list_node):
    return [e.value for e in list_node.elts
            if isinstance(e, ast.Constant)]


def test_age_level_removed_and_columns_aligned():
    for path in _FILES:
        tree = _parse(path)
        header = _header_list(tree)
        row = _build_row_return(tree)
        assert header is not None, f"{path}: header list が見つからない"
        assert row is not None, f"{path}: build_row の return list が見つからない"

        header_cols = [c for c in _consts(header) if isinstance(c, str)]
        assert "C:Age Level" not in header_cols, f"{path}: header に C:Age Level が残存"

        row_consts = [str(c) for c in _consts(row)]
        assert "6+" not in row_consts, f"{path}: build_row に Age Level値 '6+' が残存"

        assert len(header.elts) == len(row.elts), (
            f"{path}: 列ズレ! header {len(header.elts)} != row {len(row.elts)} "
            f"(Age Level 除去で header/row の片方しか消していない=出品破壊)")
