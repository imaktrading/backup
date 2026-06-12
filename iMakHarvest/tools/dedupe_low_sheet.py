"""LOW シートの ASIN 重複を安全に解消 (= 既存データ品質 cleanup).

2026-06-12 user 指示: LOW に元々あった 48 ASIN 重複を解消。

安全ルール (= live listing を絶対壊さない):
  - 重複グループ内で **eBay item ID (B列) が入った行 = 出品中** は残す。
  - **B列が空の重複行のみ削除** (= 未出品の untracked な重複コピー)。
  - グループに ID 行が複数 (= eBay 上で同一商品が二重出品) → ID 行は消さず、
    空 ID 行のみ削除。 二重出品自体は eBay 側 end が必要なので別途報告。
  - 削除は row index 降順。

実行:
  python tools/dedupe_low_sheet.py --dry-run
  python tools/dedupe_low_sheet.py
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import gspread  # noqa: E402
from google.oauth2.service_account import Credentials  # noqa: E402

from sheet_writer import CREDS_PATH, SCOPES, LOW_SHEET_ID, LISTINGS_GID  # noqa: E402

COL_URL = 1
COL_EBAY_ID = 2
COL_KEY = 35


def _asin(u):
    m = re.search(r"/dp/([A-Z0-9]{10})", u or "", re.I)
    return m.group(1).upper() if m else None


def _cell(r, c):
    return (r[c - 1].strip() if len(r) >= c else "")


def _open_low_ws():
    creds = Credentials.from_service_account_file(CREDS_PATH, scopes=SCOPES)
    gc = gspread.authorize(creds)
    for w in gc.open_by_key(LOW_SHEET_ID).worksheets():
        if w.id == LISTINGS_GID:
            return w
    raise RuntimeError("LOW worksheet not found")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    ws = _open_low_ws()
    lv = ws.get_all_values()

    groups: dict[str, list[dict]] = {}
    for i, r in enumerate(lv[1:], start=2):
        if not r or not _cell(r, COL_URL):
            continue
        a = _asin(_cell(r, COL_URL))
        if not a:
            continue
        groups.setdefault(a, []).append({
            "row": i, "ebay_id": _cell(r, COL_EBAY_ID), "key": _cell(r, COL_KEY),
        })
    dups = {a: v for a, v in groups.items() if len(v) > 1}

    delete_rows: list[dict] = []
    multi_id_flag: list[dict] = []
    for a, rows in dups.items():
        id_rows = [x for x in rows if x["ebay_id"]]
        blank_rows = [x for x in rows if not x["ebay_id"]]
        # 空 ID 行は削除対象 (= ID 行が残るので ASIN は消えない)
        if id_rows:
            for b in blank_rows:
                delete_rows.append({"asin": a, "row": b["row"], "key": b["key"]})
        else:
            # ID 行ゼロ (= 今回 0 件想定) → 先頭1行残し他削除
            for b in blank_rows[1:]:
                delete_rows.append({"asin": a, "row": b["row"], "key": b["key"]})
        if len(id_rows) >= 2:
            multi_id_flag.append({"asin": a, "key": id_rows[0]["key"],
                                  "ebay_ids": [x["ebay_id"] for x in id_rows],
                                  "rows": [x["row"] for x in id_rows]})

    rows_desc = sorted({d["row"] for d in delete_rows}, reverse=True)
    print(f"[dedupe-low] dup ASIN={len(dups)} / 削除対象(空ID重複行)={len(rows_desc)} "
          f"(dry_run={args.dry_run})", flush=True)
    for d in sorted(delete_rows, key=lambda x: x["row"]):
        print(f"  del row{d['row']} asin={d['asin']} key={d['key']!r}", flush=True)
    print(f"\n[dedupe-low] [!] 複数 eBay ID (= eBay側で二重出品、 シートでは解消不可) {len(multi_id_flag)}件:", flush=True)
    for m in multi_id_flag:
        print(f"  {m['asin']} key={m['key']!r} ids={m['ebay_ids']} rows={m['rows']}", flush=True)

    deleted = 0
    if rows_desc and not args.dry_run:
        for r in rows_desc:
            try:
                ws.delete_rows(r)
                deleted += 1
                time.sleep(0.6)
            except Exception as e:
                print(f"  WARN delete row {r}: {e!r}", flush=True)
    print(f"\n[dedupe-low] deleted={deleted}", flush=True)

    (ROOT / "debug" / "dedupe_low_result.json").write_text(json.dumps({
        "dry_run": args.dry_run, "dup_asin": len(dups),
        "delete_rows": delete_rows, "multi_id_flag": multi_id_flag, "deleted": deleted,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
