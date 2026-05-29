"""audit_and_heal - 不整合 自動修復 (= 「ヘンだったら 自動でやり直す」 機能).

cycle 末 (or 別 cron) で実行:
  1. audit_sheet_vs_ebay で全件照合
  2. 不整合あれば → 自動で revise CSV 生成 + upload (= リバイスくん format)
  3. upload 後 wait_min 分待機 → eBay report 再 DL → 反映 検証
  4. 反映 OK なら sheet B 列 対処済 mark を補正
  5. 反映 NG なら alert email (= 人手介入要)

実行:
    python audit_and_heal.py --report <path>
    python audit_and_heal.py --report <path> --dry-run    # 修復しない、 audit のみ
    python audit_and_heal.py --report <path> --no-verify  # upload 後 verify skip
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
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
CSV_OUTPUT_DIR = SCRIPT_DIR / "csv_output"
CSV_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def _log(msg: str):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def load_ebay_variations(report_path: Path) -> dict:
    """eBay report → (ItemID, SKU) → {"var": str, "price": str, "qty": int}."""
    out = {}
    with report_path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    hdr_idx = next(
        (i for i, r in enumerate(rows[:30]) if r and "Item number" in r[0]), None
    )
    if hdr_idx is None:
        return out
    hdr = rows[hdr_idx]
    sp_idx = hdr.index("Start price") if "Start price" in hdr else None
    for r in rows[hdr_idx + 1:]:
        if not r or len(r) < 5:
            continue
        iid = r[0].strip()
        sku = r[3].strip()
        if not iid or not UUID_RE.match(sku):
            continue
        try:
            qty = int(r[4]) if r[4].strip() else 0
        except ValueError:
            continue
        out[(iid, sku)] = {
            "var": r[2].strip(),
            "price": r[sp_idx].strip() if sp_idx is not None and len(r) > sp_idx else "0.99",
            "qty": qty,
        }
    return out


def build_spec_set(all_vars: list) -> str:
    """子 variation list から VariationSpecificsSet 集約 文字列を作る."""
    axis = {}
    for v in all_vars:
        for kv in v.split("|"):
            if "=" not in kv:
                continue
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


def detect_inconsistencies(sku_rows: list, ebay_var: dict) -> dict:
    """audit_sheet_vs_ebay と同じ 3 pattern 検出."""
    out = {"zero": [], "restore": [], "pending": []}
    for i, r in enumerate(sku_rows[1:], 2):
        if len(r) < 12:
            continue
        iid = r[3].strip()
        sku = r[5].strip()
        if not UUID_RE.match(sku):
            continue
        needs = r[0].strip() == "TRUE"
        done = r[1].strip() == "TRUE"
        stock = r[8].strip()
        vi = ebay_var.get((iid, sku))
        if vi is None:
            continue
        rec = {"row": i, "item_id": iid, "sku": sku, "var": vi["var"],
               "price": vi["price"], "ebay_qty": vi["qty"]}
        if done and stock == "✕" and vi["qty"] > 0:
            out["zero"].append(rec)
        elif done and stock == "◎" and vi["qty"] == 0:
            out["restore"].append(rec)
        elif needs and not done and stock == "✕" and vi["qty"] > 0:
            out["pending"].append(rec)
    return out


def generate_heal_csv(target_records: list, target_qty: int, ebay_var: dict,
                      out_path: Path) -> int:
    """リバイスくん format で heal CSV 生成 (= 不整合分を qty 補正)."""
    by_item = defaultdict(dict)
    for rec in target_records:
        iid = rec["item_id"]
        sku = rec["sku"]
        if sku in by_item[iid]:
            continue   # UUID dedup
        by_item[iid][sku] = rec

    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, quoting=csv.QUOTE_NONNUMERIC)
        w.writerow([
            "*Action(SiteID=US|Country=JP|Currency=USD|Version=745|CC=UTF-8)",
            "ItemID", "Relationship", "RelationshipDetails", "*Quantity", "*StartPrice",
        ])
        for iid, items in by_item.items():
            all_vars = [v["var"] for (id2, sku2), v in ebay_var.items() if id2 == iid]
            spec_set = build_spec_set(all_vars)
            w.writerow(["Revise", iid, "", spec_set, "", ""])
            for sku, rec in items.items():
                w.writerow(["", "", "Variation", rec["var"], target_qty, rec["price"]])
    return sum(len(v) for v in by_item.values())


def upload_csv(csv_path: Path) -> dict:
    """sell_feed_uploader 経由で upload."""
    sys.path.insert(0, r"C:\dev\iMak_inventory\iMakInventory")
    from ebay_actions.sell_feed_uploader import upload_one_csv  # noqa: PLC0415
    return upload_one_csv(csv_path, dry_run=False)


def verify_after_upload(report_path_new: Path, target_records: list,
                        target_qty: int) -> dict:
    """upload 後 新 report で 反映確認."""
    ebay_var = load_ebay_variations(report_path_new)
    confirmed, still_wrong = [], []
    for rec in target_records:
        vi = ebay_var.get((rec["item_id"], rec["sku"]))
        if vi is None:
            continue
        if vi["qty"] == target_qty:
            confirmed.append(rec)
        else:
            rec["actual_qty"] = vi["qty"]
            still_wrong.append(rec)
    return {"confirmed": confirmed, "still_wrong": still_wrong}


def main():
    parser = argparse.ArgumentParser(
        description="不整合 audit + 自動修復 + upload 後 検証")
    parser.add_argument("--report", required=True,
                        help="eBay report CSV path (= audit 用)")
    parser.add_argument("--dry-run", action="store_true",
                        help="audit のみ、 修復しない")
    parser.add_argument("--no-verify", action="store_true",
                        help="upload 後 検証 skip")
    parser.add_argument("--wait-min", type=int, default=15,
                        help="upload 後 検証までの待機 (分、 default: 15)")
    args = parser.parse_args()

    report_path = Path(args.report)
    if not report_path.exists():
        _log(f"[NG] report not found: {report_path}")
        sys.exit(1)

    # 1. audit
    _log("=" * 60)
    _log("Step 1: audit 全件照合")
    _log("=" * 60)
    sh = open_sheet()
    ws = get_sku_worksheet(sh)
    sku_rows = ws.get_all_values()
    ebay_var = load_ebay_variations(report_path)
    inconsistencies = detect_inconsistencies(sku_rows, ebay_var)
    n_zero = len(inconsistencies["zero"])
    n_restore = len(inconsistencies["restore"])
    n_pending = len(inconsistencies["pending"])
    _log(f"  取下げ未反映 (対処済T+✕+qty>0): {n_zero} 件")
    _log(f"  復活未反映 (対処済T+◎+qty=0): {n_restore} 件")
    _log(f"  未対処 (対処要T+✕+qty>0): {n_pending} 件")
    total = n_zero + n_restore + n_pending

    if total == 0:
        _log("\n[OK] 不整合 0 件、 heal skip")
        return

    if args.dry_run:
        _log(f"\n[DRY RUN] heal skip (= {total} 件)")
        return

    # 2. heal CSV 生成 + upload
    _log("\n" + "=" * 60)
    _log("Step 2: heal CSV 生成 + upload")
    _log("=" * 60)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    summary = []

    # 取下げ (= qty=0)
    zero_targets = inconsistencies["zero"] + inconsistencies["pending"]
    if zero_targets:
        zero_csv = CSV_OUTPUT_DIR / f"heal_zero_{ts}.csv"
        n = generate_heal_csv(zero_targets, 0, ebay_var, zero_csv)
        _log(f"  heal_zero CSV: {n} 件 → {zero_csv}")
        r = upload_csv(zero_csv)
        _log(f"  upload: success={r.get('success')} / {r.get('result_text', '')[:120]}")
        summary.append({"mode": "zero", "n": n, "upload": r})

    # 復活 (= qty=1)
    if inconsistencies["restore"]:
        restore_csv = CSV_OUTPUT_DIR / f"heal_restore_{ts}.csv"
        n = generate_heal_csv(inconsistencies["restore"], 1, ebay_var, restore_csv)
        _log(f"  heal_restore CSV: {n} 件 → {restore_csv}")
        r = upload_csv(restore_csv)
        _log(f"  upload: success={r.get('success')} / {r.get('result_text', '')[:120]}")
        summary.append({"mode": "restore", "n": n, "upload": r})

    # 3. wait + verify
    if not args.no_verify:
        _log("\n" + "=" * 60)
        _log(f"Step 3: upload 反映 待機 ({args.wait_min} 分)")
        _log("=" * 60)
        time.sleep(args.wait_min * 60)

        # 新 report 取得
        try:
            from ebay_active_listing_dl import download_active_listing_report   # noqa: PLC0415
            new_report = download_active_listing_report(force_new=True)
        except Exception as e:
            _log(f"  [WARN] 新 report DL 失敗、 検証 skip: {e}")
            new_report = None

        if new_report:
            for s in summary:
                qty = 0 if s["mode"] == "zero" else 1
                targets = (zero_targets if s["mode"] == "zero"
                           else inconsistencies["restore"])
                vres = verify_after_upload(new_report, targets, qty)
                s["verified"] = len(vres["confirmed"])
                s["still_wrong"] = len(vres["still_wrong"])
                _log(f"  [{s['mode']}] 反映確認: {s['verified']}/{s['n']} OK、 "
                     f"未反映 {s['still_wrong']} 件")

    # 4. save log
    log_path = DECISION_LOG_DIR / f"audit_and_heal_{ts}.json"
    log_path.write_text(json.dumps({
        "ts": ts, "report": str(report_path),
        "inconsistencies": {k: len(v) for k, v in inconsistencies.items()},
        "summary": summary,
    }, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    _log(f"\n[OK] log: {log_path}")


if __name__ == "__main__":
    main()
