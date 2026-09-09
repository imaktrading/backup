"""商品管理シートの N 列を跨ぐ書込をソースの時点で落とす (2026-09-09 HQ窓口 [IMPLEMENT-GO])。

N は =ARRAYFORMULA((M or F)−K) の spill 出力で、**1セルでも塞ぐと全行が死ぬ**
(09-09 実害: HQ の append_rows で N1 が #REF! になり、出品中721行 + 未出品1,714行の
N が全部 空になった)。人はシートを手で触らない運用なので、次に壊すとしたら **コードだけ**。
= 書く前にここで落とせる。

今は違反 0 だが、**将来 書込経路を足した時に効く**のが目的。
HQ 側の同種テストは C:/dev/iMak しか走査しない (worktree 分離) ので、
こちらのコードを守れるのは こちらの pre-commit だけ。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 商品管理シート (HIGH / LOW) を触る .py だけを見る。ID 直書きだけでなく、
# 定数 import や worksheet 取得の呼出も拾う (ID は sheet_updater にしか無いため)
SHEET_MARKERS = ("19kj8NqWHIGP1ptQDeGePw077hpdl6dNOO-v2J10HCjk",
                 "1jF9vggbfUCddjneROMO2GGN-jTAPRbq6Qe2cbgr37B0",
                 "HIGH_SHEET_ID", "LOW_SHEET_ID", "get_listings_worksheet")
PROTECTED_COLS = {14, 40}                    # N, AN
WRITE_LINE = re.compile(r'("range"\s*:|range_name\s*=)')
A1_RANGE = re.compile(r'["\']([A-Z]{1,2})\d*(?::([A-Z]{1,2})\d*)?["\']')


def _col_num(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n


def _files_touching_listings_sheet() -> list:
    out = []
    for p in ROOT.rglob("*.py"):
        if "/tests/" in p.as_posix() or p.name.startswith("test_"):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if any(m in text for m in SHEET_MARKERS):
            out.append((p, text))
    return out


def _violations(text: str) -> list:
    bad = []
    for lineno, line in enumerate(text.splitlines(), 1):
        if not WRITE_LINE.search(line):
            continue
        for start, end in A1_RANGE.findall(line):
            a = _col_num(start)
            b = _col_num(end) if end else a
            lo, hi = min(a, b), max(a, b)
            if any(lo <= c <= hi for c in PROTECTED_COLS):
                bad.append((lineno, line.strip()[:100]))
    return bad


def test_no_write_range_covers_n_or_an_column():
    """商品管理シートを触る .py に、N(14)/AN(40) を含む書込レンジが無いこと."""
    files = _files_touching_listings_sheet()
    assert len(files) >= 3, "商品管理シートを触る .py が拾えていない (検査が空振りしている)"

    found = {}
    for path, text in files:
        v = _violations(text)
        if v:
            found[path.relative_to(ROOT).as_posix()] = v
    assert not found, (
        "N(14)/AN(40) を含む書込レンジがあります。N はシート関数の出力で、"
        "1 セル塞ぐと全行が死にます。価格は M(13) に書いてください:\n"
        + "\n".join(f"  {f}:{ln} {src}" for f, vs in found.items() for ln, src in vs)
    )


def test_detector_catches_a_wide_append():
    """検査自体が効いていることの確認 (A..AN を一括で書く形を捕まえる)."""
    assert _violations('ws.update(range_name="A2:AN2", values=rows)')
    assert _violations('cell_updates.append({"range": "N5", "values": [[1]]})')
    assert _violations('cell_updates.append({"range": "M5:O5", "values": [[1]]})')
    # 守る列に届かないものは通す
    assert not _violations('cell_updates.append({"range": "A5:L5", "values": [[1]]})')
    assert not _violations('cell_updates.append({"range": "M5", "values": [[1]]})')
    assert not _violations('cell_updates.append({"range": "AO5", "values": [[1]]})')
