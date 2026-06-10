"""reverse_audit — 意図状態 (sheet D=○) vs 実 eBay 状態 (qty>0) の reconciliation.

HQ 2026-06-10 FINAL 指示 D + confirm 指示 B 準拠:
- 「取下げ義務 persist」 の最後の砦
- 「再発しないこと」 の唯一の客観証拠 (= 継続乖離 0 件)
- 初回実行は 「乖離 0 件」 を目標にしない (= 5 週間分の既存乖離を全列挙して鳥瞰、 fail-OPEN 隠ぺい禁止)
- read-only 突合 + critical alert のみ。 auto-fix は Phase 2 で別検討。

統合先: run_cycle.py の `--sheet both` cycle (毎日 09:30) 末尾の phase として呼出。
4h cycle (--sheet-label SHEET 単一 mode) では skip (= API quota / 実行時間考慮、 日次で十分)。

出力:
- `decision_log/reverse_audit_<ts>.jsonl`: 不整合 entry の機械可読 log
- 返り値: {"mismatch_count": N, "by_sheet": {...}, "by_supplier": {...}, "items": [...]}

★ HQ Phase 1.6 affirm #2 backstop 機能:
- newly_sold burst HOLD (= 6/3 偽 OOS 95 件型対策) は閾値 30 件で発火、 22-29 件帯は通過
- このとき burst guard が発火しなかった場合 (= 通過した取下げ漏れ) も、 sheet D は newly_sold で
  ○ マーク済 → 取下げ未送なら eBay qty>0 が残る → **次 09:30 cycle の reverse_audit で必ず catch**
- = burst guard (予防) + reverse_audit (検知) の 2 段防御で隙間を埋める設計
- burst HOLD された entry (= 取下げ実行されず action_required.jsonl 残存) も同様に backstop:
  sheet D=○ 維持、 eBay qty>0 残存 → reverse_audit が検出 → email alert で人手 release 誘導
- 「予防が空振りした」 失敗モードも 「検知が catch」 する relationship を sheet+eBay 突合で物理担保
"""
from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from sheet_updater import (  # noqa: E402
    HIGH_SHEET_ID,
    LOW_SHEET_ID,
    open_sheet_by_id,
    get_listings_worksheet,
    read_listings_rows,
)

DECISION_LOG_DIR = ROOT_DIR / "decision_log"
SOLD_MARKERS = ("○", "〇")


def _detect_supplier(url: str) -> str:
    u = (url or "").lower()
    if "mercari" in u:
        return "mercari"
    if "amazon" in u:
        return "amazon"
    if "fril" in u:
        return "fril"
    if "snkrdunk" in u:
        return "snkrdunk"
    return "other"


def _fetch_ebay_qty_map() -> dict:
    """eBay GetSellerList で active listing 全件取得 → {item_id: qty} map.

    iMakeBayAPI/inventory_monitor/ebay_active_listing_via_trading_api を流用。
    """
    monitor_path = ROOT_DIR.parent / "iMakeBayAPI" / "inventory_monitor"
    if str(monitor_path) not in sys.path:
        sys.path.insert(0, str(monitor_path))
    from ebay_active_listing_via_trading_api import fetch_all_active_via_trading_api  # noqa: PLC0415

    items = fetch_all_active_via_trading_api()
    qty_map = {}
    for it in items:
        iid = str(it.get("item_number") or it.get("item_id") or "").strip()
        if not iid:
            continue
        try:
            qty = int(it.get("available_qty") or 0)
        except (TypeError, ValueError):
            qty = 0
        qty_map[iid] = qty
    return qty_map


def run_reverse_audit(
    high_sheet_id: Optional[str] = None,
    low_sheet_id: Optional[str] = None,
    write_log: bool = True,
) -> dict:
    """逆方向 reconciliation 実行 (= sheet D=○ + eBay active qty>0 検出).

    Returns: {
        "ts": "...",
        "mismatch_count": N,
        "by_sheet":    {"HIGH": ..., "LOW": ...},
        "by_supplier": {"mercari": ..., "amazon": ..., ...},
        "items": [
            {"sheet": "HIGH", "row_index": 25, "item_id": "...",
             "ebay_qty": 1, "supplier": "mercari", "url": "...", "title": "..."},
            ...
        ],
        "elapsed_sec": float,
        "log_path": str | None,
    }
    """
    t0 = time.time()
    h_id = high_sheet_id or HIGH_SHEET_ID
    l_id = low_sheet_id or LOW_SHEET_ID

    print("  [reverse_audit] Step 1: eBay active listing 全件取得...", flush=True)
    qty_map = _fetch_ebay_qty_map()
    print(f"  [reverse_audit] eBay active: {len(qty_map)} 件 ({time.time()-t0:.0f}s)", flush=True)

    print("  [reverse_audit] Step 2: HIGH/LOW スプシ D 列読込...", flush=True)
    all_rows = []
    for label, sid in [("HIGH", h_id), ("LOW", l_id)]:
        try:
            sh = open_sheet_by_id(sid)
            ws = get_listings_worksheet(sh)
            rows = read_listings_rows(ws, only_with_url=False)
            for r in rows:
                all_rows.append({"sheet": label, **r})
            print(f"  [reverse_audit] {label}: {len(rows)} 行", flush=True)
        except Exception as e:
            print(f"  [!] [reverse_audit] {label} 読込失敗: {type(e).__name__}: {e}", flush=True)
            # sheet 読込失敗 = fail-CLOSED で audit 中断 (= 部分結果を出すと「ゼロ件」 と誤読される)
            return {
                "ts": datetime.now().isoformat(timespec="seconds"),
                "mismatch_count": -1,
                "error": f"sheet_read_failed: {label} {type(e).__name__}",
                "elapsed_sec": time.time() - t0,
                "log_path": None,
            }

    print("  [reverse_audit] Step 3: 乖離検出 (D=○ + eBay qty>0)...", flush=True)
    items = []
    for r in all_rows:
        iid = (r.get("item_id") or "").strip()
        d_col = (r.get("current_sold") or "").strip()
        if not iid:
            continue
        if d_col not in SOLD_MARKERS:
            continue
        qty = qty_map.get(iid)
        if qty is not None and qty > 0:
            items.append({
                "sheet":      r["sheet"],
                "row_index":  r.get("row_index", -1),
                "item_id":    iid,
                "ebay_qty":   qty,
                "supplier":   _detect_supplier(r.get("url", "")),
                "url":        r.get("url", "")[:200],
                "title":      (r.get("title") or "")[:80],
            })

    from collections import Counter  # noqa: PLC0415
    result = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "mismatch_count": len(items),
        "by_sheet":    dict(Counter(it["sheet"] for it in items)),
        "by_supplier": dict(Counter(it["supplier"] for it in items)),
        "items":       items,
        "elapsed_sec": time.time() - t0,
        "log_path":    None,
    }

    # decision_log への書込 (= 機械可読 + 履歴保全)
    if write_log:
        DECISION_LOG_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_path = DECISION_LOG_DIR / f"reverse_audit_{ts}.jsonl"
        with open(log_path, "w", encoding="utf-8") as f:
            # ヘッダ entry: 集計
            f.write(json.dumps({
                "kind": "summary",
                "ts": result["ts"],
                "mismatch_count": result["mismatch_count"],
                "by_sheet": result["by_sheet"],
                "by_supplier": result["by_supplier"],
                "elapsed_sec": result["elapsed_sec"],
            }, ensure_ascii=False) + "\n")
            # 各 entry
            for it in items:
                f.write(json.dumps({"kind": "mismatch", **it},
                                    ensure_ascii=False) + "\n")
        result["log_path"] = str(log_path)

    print(f"  [reverse_audit] 乖離: {result['mismatch_count']} 件 "
          f"sheet 別 {result['by_sheet']} supplier 別 {result['by_supplier']}", flush=True)
    return result


if __name__ == "__main__":
    res = run_reverse_audit()
    print(f"\n=== reverse_audit 結果 ===")
    print(f"  乖離: {res['mismatch_count']} 件")
    print(f"  by_sheet: {res['by_sheet']}")
    print(f"  by_supplier: {res['by_supplier']}")
    print(f"  log: {res.get('log_path')}")
    print(f"  elapsed: {res.get('elapsed_sec', 0):.1f}s")
