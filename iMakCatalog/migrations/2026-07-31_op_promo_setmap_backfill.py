"""OP promo 2 セット set_name_ebay 埋め (Advisor GO 2026-07-31).

依頼:
  - iMak_data/catalog/requests/2026-07-30_audit_catalog_fix_tcg_response.md ①
    プロモーションカードセット → Promo Cards (13件)
  - iMak_data/catalog/requests/2026-07-30_pdca_catalog_queue_tcg_response.md A-1
    始めようキャンペーン プロモーションパック → Promo Cards (14件)

flow:
  1. filter_map は yaml (ebay_filter_map/one_piece.yaml) に追記済 + loader で登録済
  2. 本 migration は既存 products 行の specs.set_name_ebay を api.derive_set_name_ebay で
     再計算し、fail_closed_no_map → filter_map_backfill_20260731 に昇格
  3. b_layer_status に verified_auto で記録

実行:
  python iMakCatalog/migrations/2026-07-31_op_promo_setmap_backfill.py           # dry-run
  python iMakCatalog/migrations/2026-07-31_op_promo_setmap_backfill.py --commit  # 適用
"""
from __future__ import annotations
import argparse
import json
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import api  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

DB_PATH = Path(api._DB_PATH)
NOW = datetime.now().isoformat()
CAT = "one_piece_tcg"
SRC_TAG = "filter_map_backfill_20260731"

TARGETS = [
    "プロモーションカードセット",
    "始めようキャンペーン プロモーションパック",
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()

    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    total_by_set: dict[str, int] = {}
    updated_by_set: dict[str, int] = {}
    filled_after: dict[str, int] = {}

    if args.commit:
        backup = DB_PATH.with_name(
            DB_PATH.name + ".pre_promo_setmap_backfill_"
            + datetime.now().strftime("%Y%m%d_%H%M%S"))
        shutil.copy2(DB_PATH, backup)
        print(f"backup: {backup.name}")

    for set_official in TARGETS:
        rows = cur.execute(
            "SELECT id, product_id, set_name_official, specs FROM products "
            "WHERE category=? AND set_name_official=?",
            (CAT, set_official),
        ).fetchall()
        total_by_set[set_official] = len(rows)
        updated_by_set[set_official] = 0
        filled_after[set_official] = 0
        print(f"=== {set_official!r}: {len(rows)} rows ===")
        for r in rows:
            try:
                d = json.loads(r["specs"]) if r["specs"] else {}
            except Exception:
                d = {}
            before_val = d.get("set_name_ebay")
            before_src = d.get("set_name_ebay_source")
            clean = api.derive_set_name_ebay(CAT, r["set_name_official"], r["product_id"])
            new_val = clean or ""
            new_src = SRC_TAG if clean else "fail_closed_no_map"
            if new_val:
                filled_after[set_official] += 1
            if before_val == new_val and before_src == new_src:
                continue
            updated_by_set[set_official] += 1
            print(f"   {r['product_id']}: "
                  f"{before_val!r}({before_src}) -> {new_val!r}({new_src})")
            if args.commit:
                d["set_name_ebay"] = new_val
                d["set_name_ebay_source"] = new_src
                cur.execute(
                    "UPDATE products SET specs=?, updated_at=? WHERE id=?",
                    (json.dumps(d, ensure_ascii=False), NOW, r["id"]),
                )
                # b_layer_status 記録 (テーブル未作成環境ではスキップ)
                try:
                    cur.execute(
                        "INSERT INTO b_layer_status "
                        "(product_id_ref, category, product_code, field, status, "
                        " oracle, checked_at, note) "
                        "VALUES (?, ?, ?, 'set_name_ebay', ?, ?, ?, ?) "
                        "ON CONFLICT(product_id_ref, field) DO UPDATE SET "
                        "status=excluded.status, oracle=excluded.oracle, "
                        "checked_at=excluded.checked_at, note=excluded.note",
                        (r["id"], CAT, r["product_id"],
                         "verified_auto" if clean else "unverified",
                         SRC_TAG, NOW, "OP promo set filter_map backfill"),
                    )
                except sqlite3.OperationalError:
                    pass
    if args.commit:
        con.commit()
    con.close()

    print()
    print("=== summary ===")
    for k in TARGETS:
        print(f"   {k!r}: total={total_by_set[k]} "
              f"updated={updated_by_set[k]} filled_after={filled_after[k]}")
    if not args.commit:
        print("\n  (DRY-RUN: --commit で適用)")


if __name__ == "__main__":
    main()
