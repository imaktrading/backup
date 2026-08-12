"""tools/purge_ended_listing_rows.py — eBay 出品が終了した行を バックアップ後に削除する。

対象: HIGH/LOW 商品管理シートの行のうち、**itemID を持つが eBay に active で存在しない**もの。
出品が無い = 売れない = 取下げ漏れになりようがないため、監視し続けるのは仕入元への無駄アクセス。

安全機構:
  - **1 行ずつ GetItem で実確認**し、**Active が 1 つでも混ざっていたら対象から外す**
    (active listing report に載らないだけの生きた出品を消すと、監視の穴 = fail-OPEN を作るため)
  - 削除前に **同 spreadsheet 内のバックアップタブへ全列コピー** (行番号・削除時刻付き)。
    バックアップ書込に失敗したら **削除しない**
  - 削除は **行番号の大きい順** (削除による行ズレを回避)
  - dry-run 既定。--execute で実削除

使い方:
  python -m tools.purge_ended_listing_rows                 # dry-run (対象確認のみ)
  python -m tools.purge_ended_listing_rows --sheet low     # 片側だけ
  python -m tools.purge_ended_listing_rows --execute       # バックアップ + 削除
"""
from __future__ import annotations

import argparse
import csv
import glob
import os
import re
import sys
import time
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import sheet_updater as su  # noqa: E402
from ebay_actions.trading_api_client import _call_trading, load_access_token  # noqa: E402

REPORT_GLOB = r"C:\Users\imax2\local_data\iMakInventory\ebay_active_listing_dl\*.csv"


def load_active_ids() -> set:
    path = sorted(glob.glob(REPORT_GLOB), key=os.path.getmtime)[-1]
    ids = set()
    with open(path, encoding="utf-8", errors="replace") as f:
        for r in csv.reader(f):
            if r and r[0].strip().isdigit() and len(r[0].strip()) >= 11:
                ids.add(r[0].strip())
    print(f"[report] {os.path.basename(path)} / active {len(ids)} listings")
    return ids


def ebay_status(item_id: str, token: str) -> str:
    """Active / Completed / ERR:<code> を返す。判定できなければ 'UNKNOWN'。"""
    xml = ('<?xml version="1.0" encoding="utf-8"?>'
           '<GetItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">'
           f"<ItemID>{item_id}</ItemID><DetailLevel>ReturnAll</DetailLevel></GetItemRequest>")
    res = _call_trading("GetItem", xml, access_token=token, raw_xml_cap=None, timeout=30)
    x = res.get("raw_xml") or ""
    m = re.search(r"<ListingStatus>(\w+)</ListingStatus>", x)
    if m:
        return m.group(1)
    code = res.get("error_code")
    if code:
        return f"ERR:{code}"
    return "UNKNOWN"


def collect(ws, active: set) -> list:
    rows = su.read_listings_rows(ws, start_row=2, end_row=None, only_with_url=False)
    out = []
    for r in rows:
        iid = (r.get("item_id") or "").strip()
        if not iid or iid == "9999":
            continue          # 未出品 / 出品対象外 FLG は触らない
        if iid in active:
            continue
        out.append({"row_index": r["row_index"], "item_id": iid,
                    "title": (r.get("title") or "")[:40], "url": (r.get("url") or "")[:60]})
    return out


def backup_and_delete(sh, ws, label: str, targets: list, execute: bool) -> dict:
    """バックアップタブへ全列コピー → 行削除 (大きい行番号から)。"""
    if not targets:
        return {"backed_up": 0, "deleted": 0}
    all_values = ws.get_all_values()
    header = all_values[0] if all_values else []
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    tab_name = f"deleted_{label}_{stamp}"
    payload = [["元row", "削除時刻", "eBay状態"] + header]
    for t in targets:
        src = all_values[t["row_index"] - 1] if len(all_values) >= t["row_index"] else []
        payload.append([t["row_index"], stamp, t.get("status", "")] + src)
    if not execute:
        print(f"  [{label}] DRY-RUN: backup tab '{tab_name}' に {len(targets)} 行を退避 → 削除 (未実行)")
        return {"backed_up": 0, "deleted": 0, "tab": tab_name}

    bws = sh.add_worksheet(title=tab_name, rows=len(payload) + 10,
                           cols=max(len(header) + 3, 10))
    bws.update(range_name=f"A1:{su._col_letter(len(payload[0]))}{len(payload)}",
               values=payload, value_input_option="RAW")
    written = len(bws.col_values(1)) - 1          # ヘッダ除く
    if written < len(targets):                    # ★ 退避できていなければ削除しない
        raise RuntimeError(f"backup 不完全 ({written}/{len(targets)}) のため削除中止 (tab={tab_name})")
    print(f"  [{label}] backup OK: '{tab_name}' に {written} 行")

    # ★ 2026-08-12: 1 行ずつ delete_rows すると書込リクエストが行数分発生し、
    #   Sheets の「Write requests per minute per user」(60/分) を超えて 429 で中断する
    #   (実際に 117 行の途中で停止)。**1 回の batch_update に deleteDimension をまとめる**。
    #   行番号の大きい順に並べれば、1 リクエスト内でも行ズレは起きない。
    reqs = [{"deleteDimension": {"range": {
                "sheetId": ws.id, "dimension": "ROWS",
                "startIndex": t["row_index"] - 1, "endIndex": t["row_index"]}}}
            for t in sorted(targets, key=lambda x: -x["row_index"])]
    for attempt in range(4):
        try:
            sh.batch_update({"requests": reqs})
            break
        except Exception as e:
            if "429" in str(e) and attempt < 3:
                wait = 60 * (attempt + 1)
                print(f"  [{label}] 429 → {wait}s 待機して再試行 ({attempt + 1}/3)")
                time.sleep(wait)
                continue
            raise
    print(f"  [{label}] 削除 {len(reqs)} 行 (batch 1 リクエスト)")
    return {"backed_up": written, "deleted": len(reqs), "tab": tab_name}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheet", choices=("high", "low", "both"), default="both")
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--limit", type=int, default=None, help="確認する件数上限 (試験用)")
    args = ap.parse_args()

    active = load_active_ids()
    token = load_access_token()
    targets = []
    if args.sheet in ("high", "both"):
        targets.append(("HIGH", su.HIGH_SHEET_ID))
    if args.sheet in ("low", "both"):
        targets.append(("LOW", su.LOW_SHEET_ID))

    grand = {}
    for label, sid in targets:
        sh = su.open_sheet_by_id(sid)
        ws = su.get_listings_worksheet(sh, gid=su.LISTINGS_GID)
        cands = collect(ws, active)
        if args.limit:
            cands = cands[:args.limit]
        print(f"[{label}] 候補 {len(cands)} 行 → eBay で 1 件ずつ確認中...")
        confirmed, alive, unknown = [], [], []
        for i, c in enumerate(cands, 1):
            st = ebay_status(c["item_id"], token)
            c["status"] = st
            if st == "Active":
                alive.append(c)
            elif st == "Completed" or st.startswith("ERR:"):
                confirmed.append(c)
            else:
                unknown.append(c)
            if i % 50 == 0:
                print(f"    {i}/{len(cands)} 確認済")
        print(f"[{label}] 終了済 {len(confirmed)} / ★Active {len(alive)} / 判定不能 {len(unknown)}")
        for a in alive[:10]:
            print(f"    ★Active のため削除対象外: row{a['row_index']} {a['item_id']} {a['title']}")
        for u in unknown[:10]:
            print(f"    判定不能のため削除対象外: row{u['row_index']} {u['item_id']} {u['status']}")
        grand[label] = backup_and_delete(sh, ws, label, confirmed, args.execute)
        grand[label].update({"candidates": len(cands), "confirmed": len(confirmed),
                             "active": len(alive), "unknown": len(unknown)})
    print("\n=== 集計 ===")
    for k, v in grand.items():
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
