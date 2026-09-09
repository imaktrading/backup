# -*- coding: utf-8 -*-
"""商品管理シート(19kj8Nq / gid 851100680)へ **N列を跨ぐ書込** をしないこと。

N は `=ARRAYFORMULA((M or F)−K)` の spill 出力で、1セル塞ぐと N1=#REF! になり
**全行の仕入値が消える**。2026-09-09 の実害はこの2経路だった:

  ① `newcand_confirm` / `psa_resource_gate` の `append_rows([[""] * 40])` → sheet_io 経由に変更
  ② `ichibankuji_to_csv` の `ws.update(range_name="A{r}:AG{r}")`         → A:M と O:AG に分割

sheet_io を通る経路は `_ColWriteGuard` が弾くが、**自分で gspread を開く script は
ガードの外**なので、ここは源流(ソース)で見張る。

★2026-09-09 追記: 最初 "A で始まるレンジ" だけを見ていたが、それでは
  `"K{r}:P{r}"` のような **途中から N を跨ぐ**書込を見逃す。列を数えて判定する。
  読み (`ws.get("A1:AB")`) は無害なので、書込のレンジ指定の行だけを見る。
"""
import os
import re

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PRODUCT_SHEET = "19kj8NqWHIGP1ptQDeGePw077hpdl6dNOO-v2J10HCjk"
N_COL = 14                      # A=1 … N=14 (仕入れ価格)
_IS_WRITE = re.compile(r"""range_name\s*=|["']range["']\s*:""")
# "A1:AG9" / "A{r}:M{r}" / f"O{a}:AM{b}" の レンジ literal
_RANGE = re.compile(r"""["']([A-Z]{1,2})[0-9{][^"':]{0,24}:([A-Z]{1,2})[0-9{]""")


def _col_num(letters):
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n


def _py_files():
    for base, dirs, files in os.walk(_ROOT):
        dirs[:] = [d for d in dirs if d not in
                   (".git", "tests", "_archive", "__pycache__", "node_modules")]
        for f in files:
            if f.endswith(".py"):
                yield os.path.join(base, f)


def test_商品管理シートを開くscriptにN列を跨ぐ書込が無い():
    bad = []
    for path in _py_files():
        try:
            src = open(path, encoding="utf-8").read()
        except (OSError, UnicodeDecodeError):
            continue
        if PRODUCT_SHEET not in src:
            continue                      # このシートを触らない script は対象外
        for i, line in enumerate(src.splitlines(), start=1):
            if not _IS_WRITE.search(line):
                continue
            for m in _RANGE.finditer(line):
                lo, hi = _col_num(m.group(1)), _col_num(m.group(2))
                if lo <= N_COL <= hi:
                    bad.append(f"{os.path.relpath(path, _ROOT)}:{i}  {line.strip()[:70]}")
    assert not bad, (
        "N列(仕入れ価格=ARRAYFORMULA)を跨ぐ書込です。N を挟んで2本に割ってください:\n  "
        + "\n  ".join(bad))


def test_判定そのものが効いているか():
    """N を跨ぐ形を見逃さない / 跨がない形を誤検出しない。"""
    def hit(line):
        return any(_col_num(m.group(1)) <= N_COL <= _col_num(m.group(2))
                   for m in _RANGE.finditer(line)) and bool(_IS_WRITE.search(line))
    assert hit('range_name=f"A{next_row}:AG{last}"')        # 2026-09-09 の実害そのもの
    assert hit('{"range": f"K{r}:P{r}"}')                   # 途中から跨ぐ形
    assert hit('range_name=f"A{r}:N{r}"')                   # N で終わる形
    assert not hit('{"range": f"A{r}:M{r}"}')               # N の手前まで
    assert not hit('{"range": f"O{r}:AM{r}"}')              # N の後ろから
    assert not hit('range_name="AC1:AG1"')                  # 補URL の見出し
    assert not hit('ws.get("A1:AB" + str(n))')              # 読みは無害
