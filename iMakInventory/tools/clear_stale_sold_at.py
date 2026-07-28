"""tools/clear_stale_sold_at.py — 在庫あり行に残った AO(売切日時) の是正 (2026-07-29 HQ 指摘)。

AO は「その行が今 売切である日時」を表す列だが、**在庫復活 (D ○→空) 時に clear していなかった**
ため、在庫あり行に過去の売切日時が残っていた (実測 39 行)。恒久修正は monitor_listings 側
(`clear_sold_at`) で入れた。本ツールは **既に残っている分の一括是正**。

安全機構 (補URL消込 tools/supervised_backup_drain.py と同じ流儀):
  - dry-run 既定、--execute で実書込
  - compare-and-clear: 書込直前に AO を re-read し、**読んだ時と同じ値のときだけ** clear
    (別プロセス/人が書き換えていたら触らない)
  - 復元アーカイブ: 消した値を decision_log/cleared_sold_at_archive.jsonl に残す (復元可)
  - 触るのは AO 列のみ (D 列/URL/M 列は不変)

使い方:
  python -m tools.clear_stale_sold_at                 # dry-run (対象一覧)
  python -m tools.clear_stale_sold_at --execute       # 実是正
  python -m tools.clear_stale_sold_at --sheet high    # 片側のみ
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import sheet_updater as su  # noqa: E402

ARCHIVE = os.path.join(SCRIPT_DIR, "decision_log", "cleared_sold_at_archive.jsonl")


def find_stale_rows(ws) -> list:
    """D 列が空 (在庫あり) かつ AO に値がある行 = 意味と実体が乖離している行。"""
    col_sold = su._col_letter(su.LISTINGS_COL_SOLD)
    col_ao = su._col_letter(su.LISTINGS_COL_SOLD_AT)
    d_vals = ws.col_values(su.LISTINGS_COL_SOLD)
    ao_vals = ws.col_values(su.LISTINGS_COL_SOLD_AT)
    item_vals = ws.col_values(su.LISTINGS_COL_ITEM_ID)
    n = max(len(d_vals), len(ao_vals))
    out = []
    for i in range(1, n):                      # 0 は header
        row = i + 1
        d = (d_vals[i] if i < len(d_vals) else "").strip()
        ao = (ao_vals[i] if i < len(ao_vals) else "").strip()
        if d or not ao:
            continue
        out.append({"row_index": row, "sold_at": ao,
                    "item_id": (item_vals[i] if i < len(item_vals) else "").strip(),
                    "d_col": col_sold, "ao_col": col_ao})
    return out


def clear_rows(ws, rows: list, sheet_label: str, execute: bool = False) -> dict:
    """compare-and-clear + アーカイブ。Returns {cleared, mismatch, entries}。"""
    if not rows:
        return {"cleared": 0, "candidates": 0, "mismatch": [], "entries": []}
    col_ao = su._col_letter(su.LISTINGS_COL_SOLD_AT)
    fresh = ws.col_values(su.LISTINGS_COL_SOLD_AT)      # 書込直前 re-read
    fresh_d = ws.col_values(su.LISTINGS_COL_SOLD)
    updates, entries, mismatch = [], [], []
    for r in rows:
        i = r["row_index"] - 1
        now_ao = (fresh[i] if i < len(fresh) else "").strip()
        now_d = (fresh_d[i] if i < len(fresh_d) else "").strip()
        if now_ao != r["sold_at"] or now_d:
            # 値が変わった / その後 売切になった → 触らない (fail-closed)
            mismatch.append({**r, "now_sold_at": now_ao, "now_d": now_d})
            continue
        updates.append({"range": f"{col_ao}{r['row_index']}", "values": [[""]]})
        entries.append({"sheet": sheet_label, "row_index": r["row_index"],
                        "col": col_ao, "sold_at": r["sold_at"], "item_id": r["item_id"],
                        "ts": datetime.now().strftime("%Y/%m/%d %H:%M:%S"),
                        "reason": "stale_sold_at_on_in_stock_row"})
    if execute and updates:
        ws.batch_update(updates, value_input_option="USER_ENTERED")
        os.makedirs(os.path.dirname(ARCHIVE), exist_ok=True)
        with open(ARCHIVE, "a", encoding="utf-8") as f:
            for e in entries:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
    return {"cleared": len(updates) if execute else 0,
            "candidates": len(updates), "mismatch": mismatch, "entries": entries}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheet", choices=("high", "low", "both"), default="both")
    ap.add_argument("--execute", action="store_true", help="実際に AO を clear する")
    args = ap.parse_args()

    targets = []
    if args.sheet in ("high", "both"):
        targets.append(("HIGH", su.HIGH_SHEET_ID))
    if args.sheet in ("low", "both"):
        targets.append(("LOW", su.LOW_SHEET_ID))

    total = 0
    for label, sid in targets:
        ws = su.get_listings_worksheet(su.open_sheet_by_id(sid), gid=su.LISTINGS_GID)
        rows = find_stale_rows(ws)
        print(f"[{label}] 在庫あり(D空) × AO有 = {len(rows)} 行")
        for r in rows[:50]:
            print(f"    row{r['row_index']:<5} iid={r['item_id'] or '(空)':<14} AO={r['sold_at']}")
        if len(rows) > 50:
            print(f"    ... 他 {len(rows) - 50} 行")
        res = clear_rows(ws, rows, label, execute=args.execute)
        if args.execute:
            print(f"[{label}] clear={res['cleared']} / mismatch(保護)={len(res['mismatch'])}")
        else:
            print(f"[{label}] DRY-RUN (--execute で実行)。clear 候補={res['candidates']} / "
                  f"mismatch(保護)={len(res['mismatch'])}")
        for m in res["mismatch"]:
            print(f"    [保護] row{m['row_index']} 読取時={m['sold_at']} / 現在={m['now_sold_at']} "
                  f"D={m['now_d'] or '(空)'}")
        total += res["candidates"]
    if args.execute:
        print(f"アーカイブ追記 → {ARCHIVE} (復元可)")
    print(f"合計 {total} 行")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
