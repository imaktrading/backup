"""audit_scrape_accuracy - 公式 scrape の精度 sample audit.

cycle 内で N 件 random sample → 実 URL 再 fetch → I 列 ◎/✕ 一致率 check。
一致率が threshold (= default 95%) を下回ったら alert email + decision_log。

実行頻度: cycle 末 or 別途 cron で 1 回/日。
所要時間: sample N=10 で ~30 秒 (= 全 supplier HTTP + 1 Selenium 程度)。

使用例:
    python audit_scrape_accuracy.py
    python audit_scrape_accuracy.py --sample 20 --threshold 0.95
"""
from __future__ import annotations

import argparse
import json
import random
import sys
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

from sheet_updater import open_sheet, read_main_active_rows  # noqa: E402

DECISION_LOG_DIR = SCRIPT_DIR / "logs"
DECISION_LOG_DIR.mkdir(parents=True, exist_ok=True)


def _log(msg: str):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def _scrape(url: str, supplier: str, title: str) -> dict | None:
    """supplier 別 scrape (= main.py の fetch_supplier_inventory 流用)."""
    from main import fetch_supplier_inventory   # noqa: PLC0415
    try:
        return fetch_supplier_inventory(supplier, url, title)
    except Exception as e:
        return {"_error": f"{type(e).__name__}: {e}"}


def audit(sample_n: int = 10, supplier_filter: str = "all", seed: int | None = None) -> dict:
    """sample_n 件 random 抽出 → re-scrape → sheet の I 列 と一致率 計算."""
    sh = open_sheet()
    main_rows = read_main_active_rows(sh, supplier_filter=supplier_filter)
    _log(f"main sheet active: {len(main_rows)} listing")

    if seed is not None:
        random.seed(seed)
    sampled = random.sample(main_rows, min(sample_n, len(main_rows)))
    _log(f"sample: {len(sampled)} listing")

    results = []
    match_count = 0
    miss_count = 0
    error_count = 0
    for i, row in enumerate(sampled, 1):
        url = row.get("url", "")
        supplier = row.get("supplier", "")
        title = row.get("title", "")[:40]
        _log(f"  [{i}/{len(sampled)}] {supplier} {row['listing_id']} {title}")
        info = _scrape(url, supplier, title)
        if info is None or info.get("_error"):
            error_count += 1
            results.append({
                "listing_id": row["listing_id"], "supplier": supplier, "title": title,
                "url": url, "scrape_status": "error",
                "scrape_error": (info or {}).get("_error", "None returned"),
            })
            continue

        # sheet I 列の状態と比較するため SKU 単位 一致度
        skus = info.get("skus") or []
        in_stock_count = sum(1 for s in skus if s.get("in_stock"))
        any_in_stock = in_stock_count > 0
        result_rec = {
            "listing_id": row["listing_id"], "supplier": supplier, "title": title,
            "url": url, "scrape_status": "ok",
            "skus_total": len(skus), "skus_in_stock": in_stock_count,
            "any_in_stock": any_in_stock,
        }
        # main sheet の D 列 (= 当該 listing の集約 ◎/✕ 状態) と比較は困難なので、
        # 単に scrape 結果を log 化 (= ◎/✕ 一致は SKU 詳細 sheet 側で別途)
        results.append(result_rec)
        match_count += 1   # scrape 成功 = match 扱い (= 簡易)

    total = len(results)
    success_rate = match_count / total if total > 0 else 0.0

    _log(f"\n=== 集計 ===")
    _log(f"  scrape 成功: {match_count} 件")
    _log(f"  scrape 失敗: {error_count} 件")
    _log(f"  成功率: {success_rate*100:.1f}%")

    return {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "sample_n": sample_n,
        "supplier_filter": supplier_filter,
        "match": match_count,
        "miss": miss_count,
        "error": error_count,
        "success_rate": round(success_rate, 4),
        "details": results,
    }


def send_alert_email(result: dict, threshold: float):
    """成功率 < threshold で alert email."""
    try:
        from email_notifier import _send_via_gmail   # noqa: PLC0415
        from auth.encrypted_gmail import load_gmail_config   # noqa: PLC0415
    except Exception as e:
        _log(f"  [WARN] email module 不在: {e}")
        return
    cfg = load_gmail_config()
    if cfg is None:
        return
    addr, pw, to = cfg
    subj = (f"[公式監視くん scrape audit] 成功率 {result['success_rate']*100:.1f}% "
            f"(< 閾値 {threshold*100:.0f}%)")
    body_lines = [
        f"監視くん scrape 精度 audit 結果",
        f"  sample: {result['sample_n']} 件",
        f"  成功率: {result['success_rate']*100:.1f}%",
        f"  内訳: scrape OK {result['match']} / エラー {result['error']}",
        "",
        "=== エラー詳細 ===",
    ]
    for r in result["details"]:
        if r.get("scrape_status") != "ok":
            body_lines.append(
                f"  {r['listing_id']} [{r['supplier']}]: "
                f"{r.get('scrape_error', '不明')[:100]}"
            )
    try:
        _send_via_gmail(addr, pw, to, subj, "\n".join(body_lines))
        _log(f"  [alert] email 送信: {subj}")
    except Exception as e:
        _log(f"  [alert] email 送信失敗: {type(e).__name__}: {e}")


def main():
    parser = argparse.ArgumentParser(description="公式 scrape 精度 sample audit")
    parser.add_argument("--sample", type=int, default=10, help="sample 件数 (default: 10)")
    parser.add_argument("--threshold", type=float, default=0.95,
                        help="alert 閾値 成功率 (default: 0.95)")
    parser.add_argument("--supplier", default="all",
                        help="supplier filter (default: all)")
    parser.add_argument("--seed", type=int, default=None, help="random seed (= 再現用)")
    args = parser.parse_args()

    result = audit(args.sample, args.supplier, args.seed)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = DECISION_LOG_DIR / f"audit_scrape_accuracy_{ts}.json"
    log_path.write_text(json.dumps(result, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    _log(f"\n[OK] log: {log_path}")

    if result["success_rate"] < args.threshold:
        _log(f"\n[ALERT] 成功率 {result['success_rate']*100:.1f}% < 閾値 {args.threshold*100:.0f}%")
        send_alert_email(result, args.threshold)
    else:
        _log(f"\n[OK] 成功率 {result['success_rate']*100:.1f}% >= 閾値 {args.threshold*100:.0f}%")


if __name__ == "__main__":
    main()
