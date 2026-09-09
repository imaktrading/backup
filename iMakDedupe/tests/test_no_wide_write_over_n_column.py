# -*- coding: utf-8 -*-
"""商品管理シート(HIGH 19kj8Nq / LOW 1jF9vgg)へ **N列を跨ぐ書込** をしないこと。

依頼: iMak_data/dedupe/requests/2026-09-09_sheet_append_must_not_touch_n_column.md

N は `=ARRAYFORMULA((M or F)−K)` の spill 出力で、1セル塞ぐと N1=#REF! になり
**全行の仕入値が消える**。2026-09-09 に HQ 側で実害 (append_rows / 幅広レンジ)。

重複くん現状:
- 書込は全て **単一セル** (`rowcol_to_a1(row, col)`、col = D=4 / AI=35 / AJ=36 / header)。
  N(14)/AN(40) を跨ぐ literal レンジも append_row(s) も **無い** (2026-09-09 grep 実測)。
- ただし HQ の `_ColWriteGuard` に相当する runtime ガードは重複くんに無いため、
  将来の混入を **源流(ソース)で見張る** (HQ の同型 test をこの worktree 用に移植)。
  HQ の test は C:/dev/iMak しか走査しない → 重複くんのコードを守れるのはこの test だけ。

対象2種:
  ① N を跨ぐ literal 書込レンジ (`range_name=` / `"range":` の "A{r}:AG{r}" 等)
  ② 商品管理シートへの append_row / append_rows (行が14列以上なら N を塞ぐ)
"""
import os
import re

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # iMakDedupe/
PRODUCT_SHEETS = (
    "19kj8NqWHIGP1ptQDeGePw077hpdl6dNOO-v2J10HCjk",  # HIGH 商品管理シート
    "1jF9vggbfUCddjneROMO2GGN-jTAPRbq6Qe2cbgr37B0",  # LOW 商品管理シート
)
N_COL = 14   # A=1 … N=14 (仕入れ価格 spill)
_IS_WRITE = re.compile(r"""range_name\s*=|["']range["']\s*:""")
_RANGE = re.compile(r"""["']([A-Z]{1,2})[0-9{][^"':]{0,24}:([A-Z]{1,2})[0-9{]""")
_APPEND = re.compile(r"\.append_rows?\s*\(")


def _col_num(letters):
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n


def _py_files():
    for base, dirs, files in os.walk(_ROOT):
        dirs[:] = [d for d in dirs if d not in
                   (".git", "tests", "__pycache__", "node_modules", "scratchpad")]
        for f in files:
            if f.endswith(".py"):
                yield os.path.join(base, f)


def _sheet_touching_sources():
    for path in _py_files():
        try:
            src = open(path, encoding="utf-8").read()
        except (OSError, UnicodeDecodeError):
            continue
        if any(sid in src for sid in PRODUCT_SHEETS):
            yield path, src


def test_商品管理シートにN列を跨ぐ書込レンジが無い():
    bad = []
    for path, src in _sheet_touching_sources():
        for i, line in enumerate(src.splitlines(), start=1):
            if not _IS_WRITE.search(line):
                continue
            for m in _RANGE.finditer(line):
                lo, hi = _col_num(m.group(1)), _col_num(m.group(2))
                if lo <= N_COL <= hi:
                    bad.append(f"{os.path.relpath(path, _ROOT)}:{i}  {line.strip()[:70]}")
    assert not bad, (
        "N列(仕入れ価格=ARRAYFORMULA)を跨ぐ書込です。N を挟んで A:M と O:… の2本に割ってください:\n  "
        + "\n  ".join(bad))


def test_商品管理シートにappend_rowが無い():
    """append は行長14以上で N を塞ぐ。重複くんは append しない (単一セル書込のみ) のが正。"""
    bad = []
    for path, src in _sheet_touching_sources():
        for i, line in enumerate(src.splitlines(), start=1):
            if _APPEND.search(line):
                bad.append(f"{os.path.relpath(path, _ROOT)}:{i}  {line.strip()[:70]}")
    assert not bad, (
        "商品管理シートを触る script に append_row(s) があります。行長14以上なら N を塞ぎ全行の\n"
        "仕入値が消えます。単一セル書込 (rowcol_to_a1) にするか、A:M と O:… に分けてください:\n  "
        + "\n  ".join(bad))


def test_判定そのものが効いているか():
    """N を跨ぐ形を見逃さない / 跨がない形を誤検出しない。"""
    def hit(line):
        return any(_col_num(m.group(1)) <= N_COL <= _col_num(m.group(2))
                   for m in _RANGE.finditer(line)) and bool(_IS_WRITE.search(line))
    assert hit('range_name=f"A{next_row}:AG{last}"')   # 2026-09-09 HQ の実害そのもの
    assert hit('{"range": f"K{r}:P{r}"}')              # 途中から跨ぐ形
    assert hit('range_name=f"A{r}:N{r}"')              # N で終わる形
    assert not hit('{"range": f"A{r}:M{r}"}')          # N の手前まで (安全)
    assert not hit('{"range": f"O{r}:AM{r}"}')         # N の後ろから (安全)
    assert not hit('ws.get("A1:AB" + str(n))')         # 読みは無害
    assert _APPEND.search('ws.append_rows([[""] * 40])')          # append 検出
    assert _APPEND.search('worksheet.append_row(row_values)')     # 単数形も
    assert not _APPEND.search('results.append(row)')              # list.append は誤検出しない
