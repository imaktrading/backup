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

    iMakeBayAPI/inventory_monitor/ebay_active_listing_via_trading_api の
    download_active_listing_via_trading_api() を流用 (= CSV 出力 + 互換 column)。
    """
    monitor_path = ROOT_DIR.parent / "iMakeBayAPI" / "inventory_monitor"
    if str(monitor_path) not in sys.path:
        sys.path.insert(0, str(monitor_path))
    from ebay_active_listing_via_trading_api import (  # noqa: PLC0415
        download_active_listing_via_trading_api,
    )
    import csv as _csv  # noqa: PLC0415

    csv_path = download_active_listing_via_trading_api()
    qty_map = {}
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        reader = _csv.DictReader(f)
        for row in reader:
            iid = (row.get("Item number") or "").strip()
            if not iid:
                continue
            try:
                qty = int(row.get("Available quantity") or 0)
            except (TypeError, ValueError):
                qty = 0
            # variation listing は同 item_id で複数行、 合計 qty で集計
            qty_map[iid] = qty_map.get(iid, 0) + qty
    return qty_map


def run_reverse_audit(
    high_sheet_id: Optional[str] = None,
    low_sheet_id: Optional[str] = None,
    write_log: bool = True,
    qty_map: Optional[dict] = None,
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
    if qty_map is None:
        qty_map = _fetch_ebay_qty_map()
    print(f"  [reverse_audit] eBay active: {len(qty_map)} 件 ({time.time()-t0:.0f}s)", flush=True)

    # 安全弁 (2026-06-11 追加): active map 空 = eBay 取得失敗 (DNS/API障害) → fail-closed。
    # ガードが無いと、 空 map のまま突合して全 D=○ 行が「乖離なし」= 偽の mismatch 0 件
    # (= fail-OPEN) になり、 取下げ漏れを見逃したまま「✅ 乖離0件」を継続証跡に積んでしまう。
    # (2026-06-11 09:30 cycle で DNS flaky 時に elapsed 4.3s / mismatch 0 = 偽0 を実観測)。
    # sibling run_ebay_down_sheet_active_audit と同じ防御。 この口座は常時 active 多数のため
    # 空 = 取得失敗で確定 (真に 0 listing になることはない)。
    if not qty_map:
        print("  [!] [reverse_audit] active map 空 = eBay 取得失敗、 fail-closed 中断", flush=True)
        return {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "mismatch_count": -1,
            "error": "ebay_active_map_empty",
            "by_sheet": {}, "by_supplier": {}, "items": [],
            "elapsed_sec": time.time() - t0,
            "log_path": None,
        }

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


# ============================================================================
# 逆方向 #2 (2026-06-10 user 指示): eBay qty=0/ended だが sheet 未売切 (D 空欄)
#   → 「在庫あり・eBay取下げ済」 レビュー用シートに書き出す。
#   背景: eBay が勝手に取下げ / ユーザー手動取下げ で eBay は qty=0 or ended だが
#         スプシ D 列は未更新 (= まだ active 扱い) のものを、 人手レビュー用に列挙。
#   方向: reverse_audit (D=○ + qty>0) の鏡像 (D 空欄 + qty=0/不在)。
#   安全弁: active map が空 = eBay 取得失敗 → fail-closed (全件を誤って ended 扱いしない)。
#   D 列は触らない (= 自動売切化しない、 user 指示で 「書き出すだけ」)。
# ============================================================================
ORPHAN_SHEET_TITLE = "在庫あり・eBay取下げ済"
ORPHAN_HEADER = ["itemID", "eBay URL", "仕入元URL", "タイトル",
                 "eBay状態", "sheet", "row", "検出日時"]


def _get_or_create_worksheet(sh, title: str):
    """worksheet を取得、 無ければ作成 (gspread)."""
    try:
        return sh.worksheet(title)
    except Exception:  # gspread.WorksheetNotFound 等
        return sh.add_worksheet(title=title, rows=200, cols=len(ORPHAN_HEADER))


def _write_orphan_sheet(sh, label: str, items: list, ts_str: str) -> int:
    """label (HIGH/LOW) の orphan items を当該 spreadsheet の review tab に上書き."""
    ws = _get_or_create_worksheet(sh, ORPHAN_SHEET_TITLE)
    data = [ORPHAN_HEADER]
    for it in items:
        ebay_url = f"https://www.ebay.com/itm/{it['item_id']}" if it["item_id"] else ""
        data.append([
            it["item_id"], ebay_url, it.get("url", ""), it.get("title", ""),
            it["ebay_state"], it["sheet"], it["row_index"], ts_str,
        ])
    ws.clear()
    last_col = chr(ord("A") + len(ORPHAN_HEADER) - 1)
    ws.batch_update(
        [{"range": f"A1:{last_col}{len(data)}", "values": data}],
        value_input_option="USER_ENTERED",
    )
    return len(items)


def run_ebay_down_sheet_active_audit(
    high_sheet_id: Optional[str] = None,
    low_sheet_id: Optional[str] = None,
    write_sheet: bool = True,
    write_log: bool = True,
    qty_map: Optional[dict] = None,
) -> dict:
    """eBay qty=0/ended × sheet D 空欄 (未売切) を検出 → review シート出力.

    Returns: {
        "ts", "orphan_count", "by_sheet", "by_state" (qty0 / ended),
        "active_total", "coverage" (D空欄 item の active map ヒット率),
        "items": [...], "elapsed_sec", "log_path", "error" (任意),
    }
    """
    t0 = time.time()
    h_id = high_sheet_id or HIGH_SHEET_ID
    l_id = low_sheet_id or LOW_SHEET_ID

    print("  [ebay_down_audit] Step 1: eBay active listing 全件取得...", flush=True)
    if qty_map is None:
        qty_map = _fetch_ebay_qty_map()
    print(f"  [ebay_down_audit] eBay active: {len(qty_map)} 件 ({time.time()-t0:.0f}s)", flush=True)

    # 安全弁: active map が空 = eBay 取得失敗。 全 sheet 行を 「ended」 と誤判定して
    # review シートを汚染するのを防ぐ → fail-closed で中断。
    if not qty_map:
        print("  [!] [ebay_down_audit] active map 空 = eBay 取得失敗、 fail-closed 中断", flush=True)
        return {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "orphan_count": -1,
            "error": "ebay_active_map_empty",
            "elapsed_sec": time.time() - t0,
            "log_path": None,
        }

    print("  [ebay_down_audit] Step 2: HIGH/LOW スプシ読込...", flush=True)
    sheets = {}
    all_rows = []
    for label, sid in [("HIGH", h_id), ("LOW", l_id)]:
        try:
            sh = open_sheet_by_id(sid)
            ws = get_listings_worksheet(sh)
            rows = read_listings_rows(ws, only_with_url=False)
            sheets[label] = sh
            for r in rows:
                all_rows.append({"sheet": label, **r})
            print(f"  [ebay_down_audit] {label}: {len(rows)} 行", flush=True)
        except Exception as e:
            print(f"  [!] [ebay_down_audit] {label} 読込失敗: {type(e).__name__}: {e}", flush=True)
            return {
                "ts": datetime.now().isoformat(timespec="seconds"),
                "orphan_count": -1,
                "error": f"sheet_read_failed: {label} {type(e).__name__}",
                "elapsed_sec": time.time() - t0,
                "log_path": None,
            }

    print("  [ebay_down_audit] Step 3: 検出 (D空欄 + eBay qty=0/不在)...", flush=True)
    items = []
    d_empty_with_id = 0
    found_in_active = 0
    for r in all_rows:
        iid = (r.get("item_id") or "").strip()
        d_col = (r.get("current_sold") or "").strip()
        if not iid:
            continue            # item_id 空欄 = 未出品 (Req1)、 対象外
        if d_col in SOLD_MARKERS:
            continue            # 既に売切マーク済 = 対象外 (reverse_audit が別途扱う)
        d_empty_with_id += 1
        qty = qty_map.get(iid)
        if qty is None:
            ebay_state = "ended/未active(要確認)"   # active 一覧に不在 = 終了/削除
        elif qty == 0:
            found_in_active += 1
            ebay_state = "qty=0"
        else:
            found_in_active += 1
            continue            # qty>0 = eBay も active = 正常 (= orphan でない)
        items.append({
            "sheet":      r["sheet"],
            "row_index":  r.get("row_index", -1),
            "item_id":    iid,
            "ebay_state": ebay_state,
            "supplier":   _detect_supplier(r.get("url", "")),
            "url":        r.get("url", "")[:200],
            "title":      (r.get("title") or "")[:80],
        })

    from collections import Counter  # noqa: PLC0415
    coverage = round(found_in_active / d_empty_with_id, 3) if d_empty_with_id else None
    result = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "orphan_count": len(items),
        "by_sheet":    dict(Counter(it["sheet"] for it in items)),
        "by_state":    dict(Counter(it["ebay_state"] for it in items)),
        "active_total": len(qty_map),
        "coverage":    coverage,
        "items":       items,
        "elapsed_sec": time.time() - t0,
        "log_path":    None,
        "sheet_writes": {},
    }

    # review シート書込 (= HIGH/LOW それぞれの spreadsheet 内 tab に上書き)
    if write_sheet:
        ts_str = result["ts"]
        for label, sh in sheets.items():
            label_items = [it for it in items if it["sheet"] == label]
            try:
                n = _write_orphan_sheet(sh, label, label_items, ts_str)
                result["sheet_writes"][label] = n
                print(f"  [ebay_down_audit] {label} review シート書込: {n} 件", flush=True)
            except Exception as e:
                print(f"  [!] [ebay_down_audit] {label} シート書込失敗: {type(e).__name__}: {e}", flush=True)
                result["sheet_writes"][label] = f"write_failed: {type(e).__name__}"

    # jsonl log (機械可読 + 履歴)
    if write_log:
        DECISION_LOG_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_path = DECISION_LOG_DIR / f"ebay_down_audit_{ts}.jsonl"
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(json.dumps({
                "kind": "summary", "ts": result["ts"],
                "orphan_count": result["orphan_count"],
                "by_sheet": result["by_sheet"], "by_state": result["by_state"],
                "active_total": result["active_total"], "coverage": coverage,
                "elapsed_sec": result["elapsed_sec"],
            }, ensure_ascii=False) + "\n")
            for it in items:
                f.write(json.dumps({"kind": "orphan", **it}, ensure_ascii=False) + "\n")
        result["log_path"] = str(log_path)

    print(f"  [ebay_down_audit] orphan: {result['orphan_count']} 件 "
          f"sheet 別 {result['by_sheet']} state 別 {result['by_state']} "
          f"(active {result['active_total']} 件, coverage {coverage})", flush=True)
    return result


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="reverse_audit / ebay_down_audit")
    ap.add_argument("--mode", choices=["reverse", "ebay_down"], default="reverse",
                    help="reverse = D=○+qty>0 (取下げ漏れ) / ebay_down = D空欄+qty=0/ended")
    ap.add_argument("--no-sheet-write", action="store_true",
                    help="ebay_down mode で review シート書込を skip (dry)")
    args = ap.parse_args()

    if args.mode == "ebay_down":
        res = run_ebay_down_sheet_active_audit(write_sheet=not args.no_sheet_write)
        print(f"\n=== ebay_down_audit 結果 ===")
        print(f"  orphan (D空欄+eBay取下げ済): {res.get('orphan_count')} 件")
        print(f"  by_sheet: {res.get('by_sheet')}")
        print(f"  by_state: {res.get('by_state')}")
        print(f"  active_total: {res.get('active_total')} / coverage: {res.get('coverage')}")
        print(f"  sheet_writes: {res.get('sheet_writes')}")
        print(f"  log: {res.get('log_path')}")
        if res.get("error"):
            print(f"  [!] error: {res['error']}")
    else:
        res = run_reverse_audit()
        print(f"\n=== reverse_audit 結果 ===")
        print(f"  乖離: {res['mismatch_count']} 件")
        print(f"  by_sheet: {res['by_sheet']}")
        print(f"  by_supplier: {res['by_supplier']}")
        print(f"  log: {res.get('log_path')}")
        print(f"  elapsed: {res.get('elapsed_sec', 0):.1f}s")
