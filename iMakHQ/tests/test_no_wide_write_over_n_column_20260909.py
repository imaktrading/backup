# -*- coding: utf-8 -*-
"""商品管理シート(19kj8Nq / gid 851100680)へ **N列を跨ぐ一括書込** をしないこと。

N は `=ARRAYFORMULA((M or F)−K)` の spill 出力で、1セル塞ぐと N1=#REF! になり
**全行の仕入値が消える**。2026-09-09 の実害はこの2経路だった:

  ① `newcand_confirm` / `psa_resource_gate` の `append_rows([[""] * 40])` → sheet_io 経由に変更
  ② `ichibankuji_to_csv` の `ws.update(range_name="A{r}:AG{r}")`         → A:M と O:AG に分割

sheet_io を通る経路は `_ColWriteGuard` が弾くが、**自分で gspread を開く script は
ガードの外**なので、ここは源流(ソース)で見張る。読み (`ws.get("A1:AB")`) は無害なので、
**書込のレンジ指定** (`range_name=` / `"range":`) の行だけを見る。
"""
import os
import re

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PRODUCT_SHEET = "19kj8NqWHIGP1ptQDeGePw077hpdl6dNOO-v2J10HCjk"
# A から始まり N 以降の列で終わるレンジ = 途中に N を含む
_WIDE = re.compile(r"""["']A(?=[0-9{])[^"':]{0,20}:(?:A[A-Z]|[N-Z])""")
_IS_WRITE = re.compile(r"""range_name\s*=|["']range["']\s*:""")


def _py_files():
    for base, dirs, files in os.walk(_ROOT):
        dirs[:] = [d for d in dirs if d not in
                   (".git", "tests", "_archive", "__pycache__", "node_modules")]
        for f in files:
            if f.endswith(".py"):
                yield os.path.join(base, f)


def test_商品管理シートを開くscriptにN列跨ぎの一括書込が無い():
    bad = []
    for path in _py_files():
        try:
            src = open(path, encoding="utf-8").read()
        except (OSError, UnicodeDecodeError):
            continue
        if PRODUCT_SHEET not in src:
            continue                      # このシートを触らない script は対象外
        for i, line in enumerate(src.splitlines(), start=1):
            if _IS_WRITE.search(line) and _WIDE.search(line):
                bad.append(f"{os.path.relpath(path, _ROOT)}:{i}  {line.strip()[:70]}")
    assert not bad, (
        "N列(仕入れ価格=ARRAYFORMULA)を跨ぐ一括書込です。A:M と O:… に割ってください:\n  "
        + "\n  ".join(bad))
