"""revise_qty_csv_generator - variation 単位の qty=0 化用 Revise CSV 生成 (Phase 4a-5).

inventory_monitor の二段確認 pass SKU を eBay FileExchange に流す Revise CSV を
生成する。listing 単位 (= 既存 iMakInventory) ではなく variation 単位:

CSV format (= eBay FileExchange Variation Revise):
    *Action(SiteID=US|Country=JP|Currency=USD|Version=745|CC=UTF-8),ItemID,SKU,*Quantity
    Revise,358275199203,253b7ad0-dd30-451a-977e-1cdbe0e8fe54,0
    Revise,358276337811,165c348f-a874-4233-8ed8-a55f22e1f891,0

実行:
    python revise_qty_csv_generator.py --dry-run
    python revise_qty_csv_generator.py --max-skus 5
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

# stdout/stderr UTF-8 化
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

from sheet_updater import open_sheet, read_sku_rows  # noqa: E402
from main import filter_two_cycle_confirmed, save_needs_action_state  # noqa: E402

CSV_OUT_DIR = SCRIPT_DIR / "csv_output"
CSV_OUT_DIR.mkdir(parents=True, exist_ok=True)
SNAPSHOT_DIR = SCRIPT_DIR / "logs" / "qty_snapshots"
SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)

# Phase 4 安全網 #2: max件数キャップ
# Takaaki さん判断 (2026-05-14): 最初 1 週間は 5 SKU/日 → 安定確認後 10 に増やす
DEFAULT_MAX_SKUS = 5

# CSV header (= iMakInventory 既存 listing 単位 format に SKU 列追加)
CSV_HEADER = "*Action(SiteID=US|Country=JP|Currency=USD|Version=745|CC=UTF-8),ItemID,SKU,*Quantity"


def read_sheet_needs_action() -> list:
    """SKU シートから「対処要 TRUE + 対処済 FALSE」の行を抽出.

    SKU シート列 (12 列):
      A(0)=対処要 (TRUE/FALSE), B(1)=対処済 (TRUE/FALSE), C(2)=対処日,
      D(3)=listing ID, E(4)=title, F(5)=eBay SKU ID (UUID), G(6)=サイズ,
      H(7)=色, I(8)=仕入元在庫, J(9)=仕入元価格, K(10)=eBay 現Qty, L(11)=自動CHK日

    Returns: [{"listing_id", "sku_id", "size", "color", "ebay_qty",
               "current_supplier_mark", "needs_action"}, ...]
    """
    sh = open_sheet()
    rows = read_sku_rows(sh)
    needs = []
    for sheet_idx, r in enumerate(rows, start=2):
        r = list(r) + [""] * max(0, 12 - len(r))
        needs_action_flag = r[0].strip().upper() in ("TRUE", "✓", "○", "OK")
        already_done_flag = r[1].strip().upper() in ("TRUE", "✓", "○", "OK")
        if not needs_action_flag or already_done_flag:
            continue
        # ebay_qty を int 化 (失敗時 0)
        try:
            ebay_qty = int(r[10]) if r[10].strip() not in ("", "-") else 0
        except ValueError:
            ebay_qty = 0
        needs.append({
            "row_index":  sheet_idx,
            "listing_id": r[3].strip(),
            "sku_id":     r[5].strip(),
            "size":       r[6].strip(),
            "color":      r[7].strip(),
            "ebay_qty":   ebay_qty,
            "needs_action": True,
        })
    return needs


def is_valid_uuid(s: str) -> bool:
    """SKU が UUID 形式か判定 (= variation listing の正規化済か)."""
    import re
    return bool(re.match(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", s or ""))


def save_qty_snapshot(needs_list: list) -> Path:
    """qty=0 化前の snapshot 保存 (Phase 4 安全網 #3、rollback 用)."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = SNAPSHOT_DIR / f"qty_snapshot_{ts}.json"
    path.write_text(json.dumps({
        "ts": datetime.now().isoformat(timespec="seconds"),
        "skus": needs_list,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def generate_revise_csv(needs_list: list) -> Path:
    """variation Revise CSV を csv_output/ に出力."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = CSV_OUT_DIR / f"revise_qty0_{ts}.csv"
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, quoting=csv.QUOTE_NONNUMERIC)
        # header
        writer.writerow([
            "*Action(SiteID=US|Country=JP|Currency=USD|Version=745|CC=UTF-8)",
            "ItemID", "SKU", "*Quantity",
        ])
        for n in needs_list:
            writer.writerow(["Revise", n["listing_id"], n["sku_id"], 0])
    return path


def main():
    parser = argparse.ArgumentParser(description="variation 単位の qty=0 Revise CSV 生成")
    parser.add_argument("--max-skus", type=int, default=DEFAULT_MAX_SKUS,
                        help=f"max 件数キャップ (default: {DEFAULT_MAX_SKUS})")
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="dry-run mode (default、--execute で実 CSV 生成)")
    parser.add_argument("--execute", action="store_true",
                        help="本番 CSV 生成 (= snapshot + CSV を csv_output/ に出力)")
    parser.add_argument("--skip-two-cycle", action="store_true",
                        help="二段確認をスキップ (= 初回 cycle 用、通常使わない)")
    args = parser.parse_args()
    is_dry_run = not args.execute

    print(f"[1/5] SKU シートから 対処要 + 対処済 FALSE 抽出")
    needs = read_sheet_needs_action()
    print(f"  対処要 (未対処): {len(needs)} 件")

    print(f"\n[2/5] UUID 形式 SKU だけ採用 (= variation 化済)")
    needs_uuid = [n for n in needs if is_valid_uuid(n["sku_id"])]
    print(f"  UUID 形式: {len(needs_uuid)} 件、UUID 未形式 (除外): {len(needs) - len(needs_uuid)} 件")

    print(f"\n[3/5] 二段確認 (Phase 4 安全網 #4)")
    if args.skip_two_cycle:
        confirmed = needs_uuid
        print(f"  --skip-two-cycle 指定 → スキップ、全 {len(confirmed)} 件採用")
    else:
        # filter_two_cycle_confirmed は main.py の all_updates 形式想定
        confirmed = filter_two_cycle_confirmed(needs_uuid)
        print(f"  二段確認 pass: {len(confirmed)} 件 (= 前 cycle でも対処要だった SKU)")

    print(f"\n[4/5] max件数キャップ ({args.max_skus} 件)")
    if len(confirmed) > args.max_skus:
        print(f"  [!] 対象 {len(confirmed)} > max {args.max_skus} → 上位 {args.max_skus} 件のみ")
        confirmed = confirmed[:args.max_skus]
    else:
        print(f"  対象 {len(confirmed)} 件 (max {args.max_skus} 以下)")

    if not confirmed:
        print(f"\n[5/5] 対象 0 件、CSV 生成スキップ")
        return

    print(f"\n[5/5] {'dry-run preview' if is_dry_run else '実 CSV 生成'}")
    if is_dry_run:
        # サンプル表示
        print(f"  CSV preview (max 10 行):")
        print(f"    {CSV_HEADER}")
        for n in confirmed[:10]:
            print(f"    Revise,{n['listing_id']},{n['sku_id']},0")
        if len(confirmed) > 10:
            print(f"    ... +{len(confirmed) - 10} 件")
    else:
        # snapshot
        snap_path = save_qty_snapshot(confirmed)
        print(f"  qty snapshot: {snap_path}")
        # CSV
        csv_path = generate_revise_csv(confirmed)
        print(f"  CSV: {csv_path}")
        print(f"  [OK] {len(confirmed)} 件 variation Revise CSV 生成完了")


if __name__ == "__main__":
    main()
