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

# max件数キャップ撤廃 (Takaaki さん判断 2026-05-14 19:53 ↓):
#   在庫管理として「順番待ちで売れる/機会損失」が許容不可。検出即全件処理が筋。
#   0 = 無制限 (= 二段確認 pass した全件を 1 cycle で upload)。
DEFAULT_MAX_SKUS = 0

# CSV header (= iMakInventory 既存 listing 単位 format に SKU 列追加)
CSV_HEADER = "*Action(SiteID=US|Country=JP|Currency=USD|Version=745|CC=UTF-8),ItemID,SKU,*Quantity"


def _read_sku_sheet_filtered(mode: str) -> list:
    """SKU シートから「対処要 TRUE + 対処済 FALSE」の行を mode 別に抽出.

    SKU シート列 (12 列):
      A(0)=対処要 (TRUE/FALSE), B(1)=対処済 (TRUE/FALSE), C(2)=対処日,
      D(3)=listing ID, E(4)=title, F(5)=eBay SKU ID (UUID), G(6)=サイズ,
      H(7)=色, I(8)=仕入元在庫, J(9)=仕入元価格, K(10)=eBay 現Qty, L(11)=自動CHK日

    mode:
      "zero"    → 仕入元 ✕ × eBay Qty > 0 (qty=0 化対象)
      "restore" → 仕入元 ◎ × eBay Qty = 0 (qty 復活対象)
    """
    sh = open_sheet()
    rows = read_sku_rows(sh)
    out = []
    for sheet_idx, r in enumerate(rows, start=2):
        r = list(r) + [""] * max(0, 12 - len(r))
        needs_action_flag = r[0].strip().upper() in ("TRUE", "✓", "○", "OK")
        already_done_flag = r[1].strip().upper() in ("TRUE", "✓", "○", "OK")
        if not needs_action_flag or already_done_flag:
            continue
        try:
            ebay_qty = int(r[10]) if r[10].strip() not in ("", "-") else 0
        except ValueError:
            ebay_qty = 0
        supplier_mark = r[8].strip()
        if mode == "zero":
            if supplier_mark != "✕" or ebay_qty <= 0:
                continue
        elif mode == "restore":
            if supplier_mark != "◎" or ebay_qty > 0:
                continue
        else:
            raise ValueError(f"unknown mode: {mode}")
        out.append({
            "row_index":  sheet_idx,
            "listing_id": r[3].strip(),
            "sku_id":     r[5].strip(),
            "size":       r[6].strip(),
            "color":      r[7].strip(),
            "ebay_qty":   ebay_qty,
            "supplier_stock_mark": supplier_mark,
            "needs_action": True,
        })
    return out


def read_sheet_needs_action() -> list:
    """qty=0 化対象 (= 仕入元 ✕ × eBay Qty > 0) を抽出."""
    return _read_sku_sheet_filtered("zero")


def read_sheet_restore_target() -> list:
    """qty 復活対象 (= 仕入元 ◎ × eBay Qty = 0) を抽出."""
    return _read_sku_sheet_filtered("restore")


def _read_sku_sheet_listing(mode: str) -> list:
    """単独 listing (= F 列 非 UUID + main_active) の qty 変更候補を抽出.

    variation Revise (SKU 列必須) の対象外。listing level Revise (3 列 format) で処理する。

    mode: "zero" (✕×Qty>0) or "restore" (◎×Qty=0)
    """
    import re as _re   # noqa: PLC0415
    _UUID = _re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
    sh = open_sheet()
    rows = read_sku_rows(sh)
    # main_active listing ids
    from sheet_updater import read_main_active_rows   # noqa: PLC0415
    main_ids = {r["listing_id"] for r in read_main_active_rows(sh, supplier_filter="all")}
    out = []
    for sheet_idx, r in enumerate(rows, start=2):
        r = list(r) + [""] * max(0, 12 - len(r))
        if r[0].strip().upper() not in ("TRUE", "✓", "○", "OK"): continue
        if r[1].strip().upper() in ("TRUE", "✓", "○", "OK"): continue
        try: ebay_qty = int(r[10]) if r[10].strip() not in ("", "-") else 0
        except ValueError: ebay_qty = 0
        sup = r[8].strip()
        f = r[5].strip()
        d = r[3].strip()
        if d not in main_ids: continue
        if _UUID.match(f): continue   # variation Revise の対象 (除外)
        if mode == "zero":
            if sup != "✕" or ebay_qty <= 0: continue
        elif mode == "restore":
            if sup != "◎" or ebay_qty > 0: continue
        else: continue
        out.append({"row_index": sheet_idx, "listing_id": d, "sku_id": f,
                    "size": r[6].strip(), "color": r[7].strip(),
                    "ebay_qty": ebay_qty, "supplier_stock_mark": sup,
                    "needs_action": True, "is_single_listing": True})
    return out


def read_sheet_listing_zero() -> list:
    return _read_sku_sheet_listing("zero")


def read_sheet_listing_restore() -> list:
    return _read_sku_sheet_listing("restore")


def generate_listing_revise_csv(items: list, target_qty: int = 0, mode: str = "zero") -> Path:
    """単独 listing 用 Revise CSV (3 列 format、SKU 列なし)."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    prefix = "revise_listing_qty0" if mode == "zero" else f"revise_listing_qty{target_qty}_restore"
    path = CSV_OUT_DIR / f"{prefix}_{ts}.csv"
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, quoting=csv.QUOTE_NONNUMERIC)
        writer.writerow([
            "*Action(SiteID=US|Country=JP|Currency=USD|Version=745|CC=UTF-8)",
            "ItemID", "*Quantity",
        ])
        # 重複 listing_id を除外 (= 単独 listing は 1 listing 1 row)
        seen = set()
        for n in items:
            lid = n["listing_id"]
            if lid in seen: continue
            seen.add(lid)
            writer.writerow(["Revise", lid, target_qty])
    return path


def is_valid_uuid(s: str) -> bool:
    """SKU が UUID 形式か判定 (= variation listing の正規化済か)."""
    import re
    return bool(re.match(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", s or ""))


def save_qty_snapshot(needs_list: list, mode: str = "zero") -> Path:
    """qty 変更前の snapshot 保存 (Phase 4 安全網 #3、rollback 用).

    mode は "zero"/"restore" を保存。rollback 時は snapshot 内の元 qty に戻す。
    """
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = SNAPSHOT_DIR / f"qty_snapshot_{ts}.json"
    path.write_text(json.dumps({
        "ts": datetime.now().isoformat(timespec="seconds"),
        "mode": mode,
        "skus": needs_list,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def generate_revise_csv(needs_list: list, target_qty: int = 0, mode: str = "zero") -> Path:
    """variation Revise CSV を csv_output/ に出力 (= リバイスくん format).

    target_qty: 全 row を共通の qty に書き換える (zero=0, restore=1)
    mode: file 名 prefix 用 ("zero" → revise_qty0_*, "restore" → revise_qtyN_*)

    2026-05-29 重大 fix: 旧 format `Action, ItemID, SKU, *Quantity` は eBay 上で
    Warning 21916619「Item level quantity will be ignored」 → variation qty 変更
    されず silent fail。 数週間分の対処済 mark が実態反映されてなかった。
    正規 format:
      1. 親行: Revise, ItemID, "", VariationSpecificsSet 集約, "", ""
      2. 子行: "", "", Variation, RelationshipDetails, qty, price
    """
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    prefix = "revise_qty0" if mode == "zero" else f"revise_qty{target_qty}_restore"
    path = CSV_OUT_DIR / f"{prefix}_{ts}.csv"

    # eBay listing report から VariationSpecificsSet + RelationshipDetails + price 構築
    from collections import defaultdict   # noqa: PLC0415
    import re   # noqa: PLC0415
    _UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)

    # 最新 eBay report を見つける
    report_dir = Path(r"C:\Users\imax2\local_data\iMakInventory\ebay_active_listing_dl")
    reports = sorted(report_dir.glob("eBay-all-active-listings-report-*.csv"),
                     key=lambda p: p.stat().st_mtime, reverse=True)
    if not reports:
        # fallback: 旧 SKU 単行 format (= 効かないが互換性のため)
        with path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f, quoting=csv.QUOTE_NONNUMERIC)
            writer.writerow([
                "*Action(SiteID=US|Country=JP|Currency=USD|Version=745|CC=UTF-8)",
                "ItemID", "SKU", "*Quantity",
            ])
            for n in needs_list:
                writer.writerow(["Revise", n["listing_id"], n["sku_id"], target_qty])
        return path

    # eBay report 読込
    with reports[0].open(encoding="utf-8-sig", newline="") as f:
        rep = list(csv.reader(f))
    hdr_idx = next((i for i, r in enumerate(rep[:30]) if r and "Item number" in r[0]), None)
    if hdr_idx is None:
        # fallback
        with path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f, quoting=csv.QUOTE_NONNUMERIC)
            writer.writerow([
                "*Action(SiteID=US|Country=JP|Currency=USD|Version=745|CC=UTF-8)",
                "ItemID", "SKU", "*Quantity",
            ])
            for n in needs_list:
                writer.writerow(["Revise", n["listing_id"], n["sku_id"], target_qty])
        return path

    hdr_r = rep[hdr_idx]
    sp_idx = hdr_r.index("Start price") if "Start price" in hdr_r else None
    data = rep[hdr_idx+1:]

    ebay_var = {}   # (iid, sku) -> {"var": str, "price": str}
    for r in data:
        if not r or len(r) < 5: continue
        iid = r[0].strip()
        sku = r[3].strip()
        if not iid or not _UUID.match(sku): continue
        var = r[2].strip()
        price = r[sp_idx].strip() if sp_idx is not None and len(r) > sp_idx else "0.99"
        ebay_var[(iid, sku)] = {"var": var, "price": price or "0.99"}

    def build_spec_set(all_vars: list) -> str:
        axis = {}
        for v in all_vars:
            for kv in v.split("|"):
                if "=" not in kv: continue
                k, val = kv.split("=", 1)
                axis.setdefault(k.strip(), []).append(val.strip())
        parts = []
        for k, vals in axis.items():
            seen, uniq = set(), []
            for v in vals:
                if v not in seen:
                    seen.add(v)
                    uniq.append(v)
            parts.append(f'{k}={";".join(uniq)}')
        return "|".join(parts)

    # ItemID 単位で集約 + UUID dedup (= sheet データ品質 issue 対応)
    by_item = defaultdict(dict)   # iid -> {sku: child_info}
    for n in needs_list:
        iid = n["listing_id"]
        sku = n["sku_id"]
        vi = ebay_var.get((iid, sku))
        if vi is None:
            continue   # eBay 上不在 = skip
        if sku in by_item[iid]:
            continue   # UUID 重複 dedup
        by_item[iid][sku] = vi

    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, quoting=csv.QUOTE_NONNUMERIC)
        writer.writerow([
            "*Action(SiteID=US|Country=JP|Currency=USD|Version=745|CC=UTF-8)",
            "ItemID", "Relationship", "RelationshipDetails", "*Quantity", "*StartPrice",
        ])
        for iid, skus_d in by_item.items():
            # 親行: 全 variation set 集約
            all_vars = [v["var"] for (id2, sku2), v in ebay_var.items() if id2 == iid]
            spec_set = build_spec_set(all_vars)
            writer.writerow(["Revise", iid, "", spec_set, "", ""])
            # 子行: 各 variation を個別 qty 変更
            for sku, info in skus_d.items():
                writer.writerow(["", "", "Variation", info["var"], target_qty, info["price"]])
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
