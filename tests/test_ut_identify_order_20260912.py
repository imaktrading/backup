# -*- coding: utf-8 -*-
"""目視は **出品済みなのに KEY が無い行** を先に出す (2026-09-12)。

実測 2026-09-12: 出品済みの Tシャツ 79行のうち UT の KEY が入っていたのは **0件**。
道具 (`ut_key_backfill`) は在ったが、目視の順番が「集めた新しい行が先」だったため、
中間タブに98件 溜まっている間 **出品済みの行が一度も画面に出なかった**。

KEY が無い出品は重複くんから見えない = 同じ物をもう一度出してしまう (fail-OPEN) ので、
まだ出していない行 (遅れても出品が1日後になるだけ) より先に片付ける。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT / "iMakHQ" / "tools", ROOT / "iMakMercari", ROOT / "iMakeBayAPI"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import ut_identify as U  # noqa: E402


def _row(item_id=""):
    r = [""] * 40
    r[0] = "https://jp.mercari.com/item/m12345678901"
    r[1] = item_id
    return r


def test_listed_rows_come_first():
    rows = [
        (2, _row(), "tab"),
        (3, _row(), "tab"),
        (1000005, _row("358000000001"), "sheet"),   # 出品済み = KEY が無いと危ない
        (1000006, _row(), "sheet"),                 # 未出品
    ]
    got = [t[0] for t in U.order_rows(rows)]
    assert got[0] == 1000005, got


def test_order_is_stable_within_a_group():
    """同じ区分の中では元の順番を崩さない (安定ソート)。"""
    rows = [(2, _row(), "tab"), (3, _row(), "tab"), (4, _row(), "tab")]
    assert [t[0] for t in U.order_rows(rows)] == [2, 3, 4]


def test_unlisted_sheet_row_is_not_prioritized():
    rows = [(1000009, _row(), "sheet"), (2, _row(), "tab")]
    assert [t[0] for t in U.order_rows(rows)] == [1000009, 2] or \
           [t[0] for t in U.order_rows(rows)] == [2, 1000009]
    # どちらでもよいが、**出品済み**より先には来ない
    rows2 = [(1000009, _row(), "sheet"), (1000010, _row("358000000002"), "sheet")]
    assert U.order_rows(rows2)[0][0] == 1000010
