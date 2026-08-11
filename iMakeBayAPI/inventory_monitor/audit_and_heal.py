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
    """Trading API ReviseInventoryStatus 経由で upload (HQ 2026-06-03 Trading API 化)."""
    sys.path.insert(0, r"C:\dev\iMak_inventory\iMakInventory")
    from ebay_actions.trading_api_uploader import upload_csv_via_trading_api  # noqa: PLC0415
    return upload_csv_via_trading_api(csv_path, dry_run=False)


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


def find_conflicting_sku_rows(sku_rows: list) -> list:
    """同じ eBay variation を指す行が複数あり、**仕入元判定が食い違っている**組を返す。

    2026-08-11 実測: montbell の size "L" と "L-R" が同一 SKU UUID を共有し (56 組 136 行)、
    片方 ✕ / 片方 ◎ になっていた。この状態を heal に通すと **サイクルを跨いで往復**する:
      cycle1: ✕ の行を見て qty=0 → cycle2: ◎ の行が「復活未反映」になり qty=1 →
      cycle3: ✕ の行が「取下げ未反映」になり qty=0 → …
    eBay API を毎回無駄打ちし、audit が永久に「不整合あり」を出して本物の取下げ漏れを埋もれさせる。
    相反する情報に対しては **どちらも自動実行しない** (fail-closed) のが正しい。

    Returns: [{"item_id", "sku", "rows": [(row_index, mark), ...]}]
    """
    groups: dict = {}
    for i, r in enumerate(sku_rows[1:], 2):
        if len(r) < 12:
            continue
        iid, sku, mark = r[3].strip(), r[5].strip(), r[8].strip()
        if not iid or not UUID_RE.match(sku) or mark not in ("◎", "✕"):
            continue
        groups.setdefault((iid, sku), []).append((i, mark))
    out = []
    for (iid, sku), rows in sorted(groups.items()):
        if len({m for _, m in rows}) > 1:      # ◎ と ✕ が同居 = 矛盾
            out.append({"item_id": iid, "sku": sku, "rows": rows})
    return out


def filter_conflicting_targets(inconsistencies: dict, conflicts: list) -> int:
    """矛盾している (listing_id, SKU) を zero / restore の両方から除去する。

    `pending` (対処要T+✕+qty>0 = 未対処の取下げ) は **除去しない**。
    そこを止めると本物の取下げ漏れを見逃すため (危険側)。
    """
    keys = {(c["item_id"], c["sku"]) for c in conflicts}
    if not keys:
        return 0
    removed = 0
    for key in ("zero", "restore"):
        before = len(inconsistencies.get(key, []))
        inconsistencies[key] = [r for r in inconsistencies.get(key, [])
                                if (r["item_id"], r["sku"]) not in keys]
        removed += before - len(inconsistencies[key])
    return removed


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

    # ★ 2026-08-11: 同一 (listing_id, SKU UUID) が zero と restore の両方に載るケースを除外。
    #   原因はシート側の重複行 (例 montbell の size "L" と "L-R" が同じ eBay variation を指し、
    #   片方 ✕ / 片方 ◎)。そのまま heal すると **同じ variation を qty=0 にして直後に qty=1 に戻す**
    #   往復になり、eBay API を毎 cycle 無駄打ちしたうえ audit が永久に「不整合あり」を出し続ける
    #   (= 本物の取下げ漏れが埋もれる)。相反する指示に対して自動アクションは取らない (fail-closed)。
    conflicts = find_conflicting_sku_rows(sku_rows)
    if conflicts:
        removed = filter_conflicting_targets(inconsistencies, conflicts)
        _log(f"  ⚠️ 重複行 conflict {len(conflicts)} 組 (同一 SKU が ✕/◎ 両方に登録) → "
             f"heal 対象から {removed} 件を保留。シート側の重複解消が必要")
        for c in conflicts[:10]:
            rows = " / ".join(f"row{i}={m}" for i, m in c["rows"])
            _log(f"     listing {c['item_id']} sku={c['sku'][:8]} : {rows}")
        n_zero = len(inconsistencies["zero"])
        n_restore = len(inconsistencies["restore"])
        _log(f"  → 保留後: 取下げ {n_zero} 件 / 復活 {n_restore} 件 (未対処 {n_pending} 件は不変)")
    total = n_zero + n_restore + n_pending

    if total == 0:
        _log("\n[OK] 不整合 0 件、 heal skip"
             + (f" (重複 conflict {len(conflicts)} 件は保留中 = 要シート修正)" if conflicts else ""))
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
