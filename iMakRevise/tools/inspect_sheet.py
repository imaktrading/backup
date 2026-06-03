"""inspect_sheet.py - 商品管理シート の header + 列充足度を確認するツール.

新ロジック (2026-05-03): D / F / N / AH / Y 列の現状確認。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

THIS = Path(__file__).resolve().parent
PROJECT = THIS.parent
sys.path.insert(0, str(PROJECT))

from revise.price_revise import (
    HEADER_ROWS,
    COL_ITEM_ID, COL_SOLD_FLAG, COL_F_PRICE, COL_FLAG,
    COL_N_PRICE, COL_CHECK_TIME, COL_CATEGORY, COL_AH_PRICE,
    load_sheet_rows, _to_float, _is_sold, _is_valid_jpy, should_revise,
)


def main():
    header, rows, _ws = load_sheet_rows()
    print(f"=== 全行: {len(rows)} (header 除く) ===")
    print(f"\n=== header ({len(header)} 列) ===")
    letters_a = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    for i, h in enumerate(header):
        if i < 26:
            col_letter = letters_a[i]
        else:
            col_letter = "A" + letters_a[i - 26]
        marker = ""
        if i == COL_ITEM_ID: marker = "  <-- ItemID"
        elif i == COL_SOLD_FLAG: marker = "  <-- D (売切)"
        elif i == COL_F_PRICE: marker = "  <-- F (出品時 ¥)"
        elif i == COL_FLAG: marker = "  <-- M (flag)"
        elif i == COL_N_PRICE: marker = "  <-- N (現在仕入 ¥)"
        elif i == COL_CHECK_TIME: marker = "  <-- O (CHK 時刻)"
        elif i == COL_CATEGORY: marker = "  <-- Y (カテゴリ)"
        elif i == COL_AH_PRICE: marker = "  <-- AH (前期 N ¥)"
        print(f"  [{i:2d}] {col_letter}: {h!r}{marker}")

    # 列充足度統計
    n_item = n_sold = n_f = n_n = n_ah = n_cat = 0
    n_F_AH_both_empty_with_N = 0  # 初期化対象 (F+AH 両空 + N 値あり)
    n_AH_with_N = 0               # AH と N 両方値あり (短期 trend 判定可)
    n_F_with_N_no_AH = 0          # F 値あり + AH 空 + N 値あり (フォールバック判定)
    n_revise_yes = 0              # should_revise = True 件数

    for row in rows:
        item_id = (row[COL_ITEM_ID] or "").strip() if len(row) > COL_ITEM_ID else ""
        sold = row[COL_SOLD_FLAG] if len(row) > COL_SOLD_FLAG else ""
        f_jpy = _to_float(row[COL_F_PRICE]) if len(row) > COL_F_PRICE else None
        n_jpy = _to_float(row[COL_N_PRICE]) if len(row) > COL_N_PRICE else None
        ah_jpy = _to_float(row[COL_AH_PRICE]) if len(row) > COL_AH_PRICE else None
        cat = (row[COL_CATEGORY] or "").strip() if len(row) > COL_CATEGORY else ""

        if item_id:
            n_item += 1
        if _is_sold(sold):
            n_sold += 1
        if _is_valid_jpy(f_jpy):
            n_f += 1
        if _is_valid_jpy(n_jpy):
            n_n += 1
        if _is_valid_jpy(ah_jpy):
            n_ah += 1
        if cat:
            n_cat += 1
        # init 対象
        if (not _is_valid_jpy(f_jpy)) and (not _is_valid_jpy(ah_jpy)) and _is_valid_jpy(n_jpy) and item_id and not _is_sold(sold):
            n_F_AH_both_empty_with_N += 1
        # AH + N (短期 trend 判定可)
        if _is_valid_jpy(ah_jpy) and _is_valid_jpy(n_jpy):
            n_AH_with_N += 1
        # F + N + AH 空 (フォールバック判定)
        if _is_valid_jpy(f_jpy) and _is_valid_jpy(n_jpy) and not _is_valid_jpy(ah_jpy):
            n_F_with_N_no_AH += 1
        # should_revise
        revise_yes, _, _, _ = should_revise(f_jpy, n_jpy, ah_jpy, sold)
        if revise_yes:
            n_revise_yes += 1

    total = len(rows)
    print(f"\n=== 列充足度 ===")
    print(f"  ItemID あり:        {n_item:4d} / {total}")
    print(f"  D = ○ (売切):       {n_sold:4d} / {total}")
    print(f"  F 値あり:           {n_f:4d} / {total}")
    print(f"  N 値あり:           {n_n:4d} / {total}")
    print(f"  AH 値あり:          {n_ah:4d} / {total}  ★監視くん AH 更新状況")
    print(f"  Y カテゴリ あり:    {n_cat:4d} / {total}")
    print()
    print(f"=== 判定パターン ===")
    print(f"  F+AH 両空 + N (init 対象):                {n_F_AH_both_empty_with_N:4d}")
    print(f"  AH + N 両方値あり (短期 trend 判定可):    {n_AH_with_N:4d}")
    print(f"  F+N + AH 空 (大局フォールバック判定):     {n_F_with_N_no_AH:4d}")
    print(f"  should_revise = True (= revise 起動):    {n_revise_yes:4d}")

    # AH 値あり sample 5 件
    print(f"\n=== AH 値あり sample 5 件 ===")
    cnt = 0
    for i, row in enumerate(rows):
        ah_jpy = _to_float(row[COL_AH_PRICE]) if len(row) > COL_AH_PRICE else None
        n_jpy = _to_float(row[COL_N_PRICE]) if len(row) > COL_N_PRICE else None
        item_id = (row[COL_ITEM_ID] or "").strip() if len(row) > COL_ITEM_ID else ""
        if _is_valid_jpy(ah_jpy):
            cat = (row[COL_CATEGORY] or "").strip() if len(row) > COL_CATEGORY else ""
            delta = (n_jpy - ah_jpy) / ah_jpy * 100 if _is_valid_jpy(n_jpy) else None
            print(f"  row{i + HEADER_ROWS + 1}: item={item_id} N={n_jpy} AH={ah_jpy} delta={delta}% cat={cat}")
            cnt += 1
            if cnt >= 5:
                break


if __name__ == "__main__":
    main()
