"""audit_duplicate_uuid - SKU 詳細 sheet で重複 UUID (= 同 listing 内同 SKU)
が複数 variation に割当てられてる データ品質 issue を検出.

検出パターン: 同 ItemID 内で同 UUID が 2+ rows に割当て (= 違う size/color)。
これは eBay revise CSV で「Duplicate custom variation label」 error 起因。

実行:
    python audit_duplicate_uuid.py
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

from sheet_updater import open_sheet, get_sku_worksheet  # noqa: E402

UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I
)

DECISION_LOG_DIR = SCRIPT_DIR / "logs"
DECISION_LOG_DIR.mkdir(parents=True, exist_ok=True)


def _log(msg: str):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def audit() -> dict:
    sh = open_sheet()
    ws = get_sku_worksheet(sh)
    sku_rows = ws.get_all_values()
    _log(f"SKU 詳細: {len(sku_rows)-1} 行")

    # (ItemID, UUID) → [rows]
    by_iid_sku = defaultdict(list)
    for i, r in enumerate(sku_rows[1:], 2):
        if len(r) < 8:
            continue
        iid = r[3].strip()
        sku = r[5].strip()
        if not UUID_RE.match(sku):
            continue
        by_iid_sku[(iid, sku)].append({
            "row": i, "item_id": iid, "sku": sku,
            "size": r[6] if len(r) > 6 else "",
            "color": r[7] if len(r) > 7 else "",
            "title": (r[4] if len(r) > 4 else "")[:50],
        })

    duplicates = []
    for (iid, sku), rows in by_iid_sku.items():
        if len(rows) >= 2:
            duplicates.append({
                "item_id": iid, "sku": sku, "count": len(rows),
                "rows": rows,
            })

    duplicates.sort(key=lambda x: (x["item_id"], x["sku"]))

    _log(f"\n=== 重複 UUID ===")
    _log(f"  発見: {len(duplicates)} 件 (= UUID 1 件あたり 2+ rows)")

    for d in duplicates[:10]:
        rows_str = ", ".join(
            f"row{r['row']} {r['size']}/{r['color']}" for r in d["rows"]
        )
        _log(f"  {d['item_id']} sku={d['sku'][:36]}: {rows_str}")
    if len(duplicates) > 10:
        _log(f"  ... +{len(duplicates) - 10} 件")

    return {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "duplicate_count": len(duplicates),
        "details": duplicates,
    }


def main():
    result = audit()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = DECISION_LOG_DIR / f"audit_duplicate_uuid_{ts}.json"
    log_path.write_text(json.dumps(result, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    _log(f"\n[OK] log: {log_path}")
    if result["duplicate_count"] > 0:
        _log(f"\n[ACTION REQUIRED] 重複 UUID {result['duplicate_count']} 件: sheet クリーンアップ要")
        _log(f"  対応: 重複側の row を delete or 新 UUID 割当 + eBay 側 SKU 再設定")
        sys.exit(1)


if __name__ == "__main__":
    main()
