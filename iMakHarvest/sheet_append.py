"""sheet_append - 商品管理シートへ **N列 と AN列 を塞がずに** 行を足す.

2026-09-09 新設 (HQ窓口 依頼 `2026-09-09_sheet_append_must_not_touch_n_column`)。

商品管理シートの **N列 (仕入れ価格)** と **AN列** は ARRAYFORMULA の spill 出力で、
**1セルでも値が入ると 列全体が #REF! になり全行が空になる**。

`ws.append_rows(rows)` は行の長さぶんの列を **左から順に**書くので、 長さが14以上あると
N列に空文字を書いて塞ぐ。 `_ColWriteGuard` の類は range 指定の書込しか見ないため
append は素通りする (HQ 側も 2026-09-09 まで素通りしていた)。

なので **append を使わず、 N と AN を避けた range を2〜3本に分けて書く**。
"""
from __future__ import annotations

# spill の出力列 (1始まり)。 ここには絶対に書かない
PROTECTED_COLS = (14, 40)      # N, AN


def _col_letter(idx: int) -> str:
    """1 -> A, 27 -> AA."""
    s = ""
    while idx > 0:
        idx, r = divmod(idx - 1, 26)
        s = chr(65 + r) + s
    return s


def split_ranges(start_col: int, end_col: int,
                 protected: tuple = PROTECTED_COLS) -> list[tuple[int, int]]:
    """[start_col, end_col] を **守る列を除いた** 連続区間に割る (純関数)."""
    out: list[tuple[int, int]] = []
    cur = start_col
    for p in sorted(protected):
        if p < start_col or p > end_col:
            continue
        if cur <= p - 1:
            out.append((cur, p - 1))
        cur = p + 1
    if cur <= end_col:
        out.append((cur, end_col))
    return out


def build_batch(rows: list[list], first_row: int,
                protected: tuple = PROTECTED_COLS) -> list[dict]:
    """append したい行から `batch_update` 用の指示を作る (純関数).

    N/AN を跨がないよう range を分け、 各 range にはその列ぶんの値だけ渡す。
    """
    if not rows:
        return []
    width = max(len(r) for r in rows)
    reqs = []
    for a, b in split_ranges(1, width, protected):
        vals = [(r + [""] * (width - len(r)))[a - 1:b] for r in rows]
        last = first_row + len(rows) - 1
        reqs.append({
            "range": f"{_col_letter(a)}{first_row}:{_col_letter(b)}{last}",
            "values": vals,
        })
    return reqs


def append_rows_safe(ws, rows: list[list], value_input_option: str = "USER_ENTERED",
                     protected: tuple = PROTECTED_COLS) -> int:
    """末尾に行を足す。 **N列/AN列には触らない**. 足した行数を返す."""
    if not rows:
        return 0
    first_row = len(ws.get_all_values()) + 1
    reqs = build_batch(rows, first_row, protected)
    # 行が足りなければ先に足す (Range exceeds grid limits 対策)
    try:
        need = first_row + len(rows) - 1 - int(getattr(ws, "row_count", 0) or 0)
        if need > 0:
            ws.add_rows(need + 200)
    except Exception:  # noqa: BLE001
        pass
    ws.batch_update(reqs, value_input_option=value_input_option)
    return len(rows)
