"""audit_sheet_vs_ebay - 公式 SKU 詳細シート と eBay report の整合性 全件 audit.

3 つの不整合パターンを検出 + alert email + decision_log 記録:
  1. 対処済T + 仕入元✕ + eBay qty>0 = 取下げ未反映 (= sheet 嘘の達成感)
  2. 対処済T + 仕入元◎ + eBay qty=0 = 復活未反映
  3. 仕入元✕ + eBay qty>0 + 対処済F = 未対処 (= cycle で出るはずだが取りこぼし監視)

cycle 末の main.py 最後で呼出し想定。 不整合 0 件なら silent、 1+ で alert。

使用例:
    python audit_sheet_vs_ebay.py --report <path>
    python audit_sheet_vs_ebay.py --report <path> --alert-threshold 5
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

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


def load_ebay_qty(report_path: Path) -> dict:
    """eBay report → (ItemID, SKU) → qty mapping."""
    out = {}
    with report_path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    hdr_idx = next(
        (i for i, r in enumerate(rows[:30]) if r and "Item number" in r[0]), None
    )
    if hdr_idx is None:
        return out
    for r in rows[hdr_idx + 1:]:
        if not r or len(r) < 5:
            continue
        iid = r[0].strip()
        sku = r[3].strip()
        if not iid or not UUID_RE.match(sku):
            continue
        try:
            out[(iid, sku)] = int(r[4]) if r[4].strip() else 0
        except ValueError:
            continue
    return out


def audit(report_path: Path) -> dict:
    """SKU 詳細 sheet と eBay report を照合、 不整合 件数 + 詳細を返却."""
    sh = open_sheet()
    ws = get_sku_worksheet(sh)
    sku_rows = ws.get_all_values()
    _log(f"SKU 詳細: {len(sku_rows)-1} 行")

    ebay_qty = load_ebay_qty(report_path)
    _log(f"eBay variation: {len(ebay_qty)} 件")

    inconsistencies = {
        "zero_not_applied": [],   # 1. 対処済T+✕+qty>0
        "restore_not_applied": [],  # 2. 対処済T+◎+qty=0
        "pending_not_handled": [],  # 3. 対処要T+✕+qty>0+対処済F
    }

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
        ebay = ebay_qty.get((iid, sku))
        if ebay is None:
            continue   # eBay 上不在 (= ended listing) は audit 対象外

        rec = {
            "row": i, "item_id": iid, "sku": sku,
            "size": r[6] if len(r) > 6 else "",
            "color": r[7] if len(r) > 7 else "",
            "title": (r[4] if len(r) > 4 else "")[:50],
            "ebay_qty": ebay,
        }
        if done and stock == "✕" and ebay > 0:
            inconsistencies["zero_not_applied"].append(rec)
        elif done and stock == "◎" and ebay == 0:
            inconsistencies["restore_not_applied"].append(rec)
        elif needs and not done and stock == "✕" and ebay > 0:
            inconsistencies["pending_not_handled"].append(rec)

    total_inconsistencies = sum(len(v) for v in inconsistencies.values())
    _log(f"\n=== 不整合 集計 ===")
    _log(f"  取下げ未反映 (対処済T+✕+qty>0): {len(inconsistencies['zero_not_applied'])} 件")
    _log(f"  復活未反映 (対処済T+◎+qty=0): {len(inconsistencies['restore_not_applied'])} 件")
    _log(f"  未対処 (対処要T+✕+qty>0): {len(inconsistencies['pending_not_handled'])} 件")
    _log(f"  計: {total_inconsistencies} 件")

    return {
        "total": total_inconsistencies,
        "details": inconsistencies,
        "ts": datetime.now().isoformat(timespec="seconds"),
    }


def send_alert_email(result: dict, report_name: str):
    """不整合 件数 > 0 なら alert email 送信."""
    try:
        from email_notifier import _send_via_gmail   # noqa: PLC0415
        from auth.encrypted_gmail import load_gmail_config   # noqa: PLC0415
    except Exception as e:
        _log(f"  [WARN] email module 不在: {e}")
        return
    cfg = load_gmail_config()
    if cfg is None:
        _log(f"  [WARN] gmail config 不在")
        return
    addr, pw, to = cfg
    det = result["details"]
    subj = (f"[公式監視くん audit] 不整合 {result['total']} 件 "
            f"(取下げ漏れ{len(det['zero_not_applied'])}/"
            f"復活漏れ{len(det['restore_not_applied'])}/"
            f"未対処{len(det['pending_not_handled'])})")
    body_lines = [
        f"監視くん cycle 末 audit 結果",
        f"  report: {report_name}",
        f"  audit time: {result['ts']}",
        "",
        "=== 不整合 内訳 ===",
    ]
    for key, label in [
        ("zero_not_applied", "取下げ未反映 (= sheet 対処済 but eBay qty>0)"),
        ("restore_not_applied", "復活未反映 (= sheet 対処済 but eBay qty=0)"),
        ("pending_not_handled", "未対処 (= 対処要 but eBay qty>0)"),
    ]:
        items = det[key]
        body_lines.append(f"\n[{label}: {len(items)} 件]")
        for it in items[:20]:
            body_lines.append(
                f"  row{it['row']} {it['item_id']} ({it['size']}/{it['color']}) "
                f"eBay_qty={it['ebay_qty']} : {it['title']}"
            )
        if len(items) > 20:
            body_lines.append(f"  ... +{len(items) - 20} 件")

    try:
        _send_via_gmail(addr, pw, to, subj, "\n".join(body_lines))
        _log(f"  [alert] email 送信: {subj}")
    except Exception as e:
        _log(f"  [alert] email 送信失敗: {type(e).__name__}: {e}")


def main():
    parser = argparse.ArgumentParser(description="SKU 詳細 vs eBay 全件 audit")
    parser.add_argument("--report", required=True, help="eBay active listing report CSV path")
    parser.add_argument("--alert-threshold", type=int, default=1,
                        help="alert 発火する不整合最低件数 (default: 1)")
    parser.add_argument("--save-log", action="store_true", default=True,
                        help="audit 結果を decision_log に保存 (default: True)")
    args = parser.parse_args()

    report_path = Path(args.report)
    if not report_path.exists():
        _log(f"[NG] report not found: {report_path}")
        sys.exit(1)

    result = audit(report_path)

    if args.save_log:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_path = DECISION_LOG_DIR / f"audit_sheet_vs_ebay_{ts}.json"
        log_path.write_text(json.dumps(result, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        _log(f"\n[OK] log: {log_path}")

    if result["total"] >= args.alert_threshold:
        _log(f"\n[ALERT] 不整合 {result['total']} 件 >= 閾値 {args.alert_threshold}、 email 通知")
        send_alert_email(result, report_path.name)
    else:
        _log(f"\n[OK] 不整合 {result['total']} 件 < 閾値 {args.alert_threshold}、 通知 skip")


if __name__ == "__main__":
    main()
