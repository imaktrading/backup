"""商品管理シートの **N列 / AN列 を塞がない** ことを守る (2026-09-09 HQ 依頼).

N は `=ARRAYFORMULA((M or F)-K)` の spill 出力で、**1セルでも値が入ると
列全体が #REF! になり全行が空になる** (2026-09-09 に実際に起きた。犯人は
`ws.append_rows([[""] * 40])`)。

このテストは2つ見る:
  ① 書込のレンジ指定が N(14) / AN(40) を跨いでいないか (HQ 側の test と同じ源流チェック)
  ② `append_row` / `append_rows` を商品管理シートに使っていないか
     (append は列を左から順に埋めるので、レンジのガードをすり抜ける)
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.offline

ROOT = Path(__file__).resolve().parents[1]
HIGH_ID = "19kj8NqWHIGP1ptQDeGePw077hpdl6dNOO-v2J10HCjk"
LOW_ID = "1jF9vggbfUCddjneROMO2GGN-jTAPRbq6Qe2cbgr37B0"
PROTECTED = (14, 40)      # N, AN
RANGE_RE = re.compile(r'(?:range_name=|"range":\s*)f?["\']([A-Z]+)\d*:([A-Z]+)')



def _col(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n


def _product_sheet_sources():
    """商品管理シート (HIGH/LOW) を触る .py だけを見る."""
    for p in ROOT.glob("*.py"):
        t = p.read_text(encoding="utf-8", errors="ignore")
        if HIGH_ID in t or LOW_ID in t:
            yield p, t


def test_no_range_write_crosses_protected_columns():
    bad = []
    for path, text in _product_sheet_sources():
        for a, b in RANGE_RE.findall(text):
            lo, hi = _col(a), _col(b)
            for p in PROTECTED:
                if lo <= p <= hi:
                    bad.append(f"{path.name}: {a}:{b} が {p}列目を含む")
    assert not bad, "N/AN を跨ぐ書込がある: " + " / ".join(bad)


def test_no_append_rows_on_the_product_sheet():
    """append は列を左から埋めるので N を塞ぐ。 sheet_append.append_rows_safe を使う.

    ★コメントや docstring の言及は数えない (ast で **実際の呼出** だけ見る)。
    """
    bad = []
    for path, text in _product_sheet_sources():
        for node in ast.walk(ast.parse(text)):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in ("append_row", "append_rows")):
                bad.append(f"{path.name}:{node.lineno}")
    assert not bad, ("商品管理シートに append を使っている (N列を塞ぐ): "
                     + ", ".join(bad))


# --------------------------------------------------------------------------
# 分割ロジック
# --------------------------------------------------------------------------
def test_split_ranges_skips_n_and_an():
    from sheet_append import split_ranges
    assert split_ranges(1, 20) == [(1, 13), (15, 20)]          # N を避ける
    assert split_ranges(1, 40) == [(1, 13), (15, 39)]          # AN も避ける
    assert split_ranges(1, 10) == [(1, 10)]                    # 手前で終わるなら1本


def test_build_batch_writes_values_without_the_protected_columns():
    from sheet_append import build_batch
    rows = [[str(i) for i in range(1, 21)]]                    # A..T の20列
    reqs = build_batch(rows, first_row=5)
    assert [r["range"] for r in reqs] == ["A5:M5", "O5:T5"]
    assert reqs[0]["values"][0] == [str(i) for i in range(1, 14)]     # A..M
    assert reqs[1]["values"][0] == [str(i) for i in range(15, 21)]    # O..T (N を飛ばす)
