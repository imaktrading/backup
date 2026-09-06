"""tools/dedupe_sku_rows.py — SKU 詳細シートの重複行を掃除する (dry-run 既定)。

重複 = 同じ (listing ID, サイズ, 色) の行が 2 行以上。**最も上の行を残し、残りを消す**。
size 空欄の行は別問題 (UUID 同期の置き土産) なので **触らない**。

原因は単独 listing の突合外れで、1 cycle 1 行ずつ append されていた
(2026-09-07 に main.py 側を修正済。本ツールはその時までに溜まった分の清算)。

安全機構:
  - 既定は dry-run。--execute で実削除
  - 消す行は logs/sku_dupe_cleanup_<ts>.json に全内容を退避 (復元可能)
  - 行番号の大きい方から消す (削除でズレない)

使い方:
    python -m tools.dedupe_sku_rows            # 確認だけ
    python -m tools.dedupe_sku_rows --execute  # 実削除
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import sys
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from sheet_updater import open_sheet, get_sku_worksheet  # noqa: E402

LOG_DIR = os.path.join(SCRIPT_DIR, "logs")


def plan_deletions(rows: list) -> tuple:
    """(削除する 1-based 行番号 list, 重複キーの内訳) を返す。size 空欄行は対象外。"""
    groups = collections.defaultdict(list)
    for i, r in enumerate(rows, 2):          # header が 1 行目
        if len(r) > 7 and r[3].strip() and r[6].strip():
            groups[(r[3].strip(), r[6].strip(), r[7].strip())].append(i)
    delete, detail = [], []
    for key, idxs in sorted(groups.items()):
        if len(idxs) > 1:
            keep = min(idxs)
            delete += [i for i in idxs if i != keep]
            detail.append({"key": key, "rows": len(idxs), "keep": keep})
    return sorted(delete), detail


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true", help="実削除 (既定は dry-run)")
    args = ap.parse_args()

    sh = open_sheet()
    ws = get_sku_worksheet(sh)
    values = ws.get_all_values()
    rows = values[1:]
    delete, detail = plan_deletions(rows)

    for d in detail:
        print(f"  {d['key']}: {d['rows']} 行 → row{d['keep']} を残して {d['rows'] - 1} 行削除")
    print(f"[dedupe] 全 {len(rows)} 行 / 削除対象 {len(delete)} 行")
    if not delete:
        return 0

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    os.makedirs(LOG_DIR, exist_ok=True)
    backup_path = os.path.join(LOG_DIR, f"sku_dupe_cleanup_{ts}.json")
    with open(backup_path, "w", encoding="utf-8") as f:
        json.dump({"ts": ts, "header": values[0],
                   "deleted": [{"row_index": i, "values": rows[i - 2]} for i in delete]},
                  f, ensure_ascii=False, indent=1)
    print(f"[dedupe] 退避: {backup_path}")

    if not args.execute:
        print("[dedupe] === DRY-RUN (削除なし、--execute で実行) ===")
        return 0

    reqs = [{"deleteDimension": {"range": {"sheetId": ws.id, "dimension": "ROWS",
                                           "startIndex": i - 1, "endIndex": i}}}
            for i in sorted(delete, reverse=True)]
    sh.batch_update({"requests": reqs})
    after = len(ws.get_all_values())
    print(f"[dedupe] 削除 {len(reqs)} 行 完了 / 残り {after - 1} 行 (header 除く)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
