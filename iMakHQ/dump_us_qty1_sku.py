"""dump_us_qty1_sku - 最新 snapshot から US/qty>=1 を抽出 + スプシ照合 + CSV 出力.

5/13 ユーザー判断: snapshot 見て手動で取下げ判断のための CSV 生成専用ツール。

抽出条件:
  - 最新 snapshot (snapshot_active_all_*.csv)
  - listing_site = US
  - quantity_available >= 1

出力列:
  category / item_id / sku / title / price_usd / views / watchers
  / quantity_available / listed_date / listing_site / in_spreadsheet

オプション:
  --fresh-snapshot: 実行前に最新 snapshot を再取得 (Selenium、約 10 分)
"""
from __future__ import annotations

import argparse
import csv
import glob
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

SNAPSHOT_DIR = r"C:\dev\iMak_data\seller_hub"
DESKTOP_DIR = r"C:\Users\imax2\OneDrive\デスクトップ"
CREDS_PATH = r"c:\dev\iMak\double-hold-421922-7c0d38d3f73d.json"
SHEET_IDS = [
    "19kj8NqWHIGP1ptQDeGePw077hpdl6dNOO-v2J10HCjk",  # 統合Hight
    "1jF9vggbfUCddjneROMO2GGN-jTAPRbq6Qe2cbgr37B0",  # 統合Low
]
SHEET_GID = 851100680


def take_fresh_snapshot() -> None:
    """seller_hub_view.py を --save --all-pages で起動 (約 10 分)."""
    print("=== 新 snapshot 取得開始 (約 10 分、Selenium で eBay scrape) ===")
    hq_dir = os.path.dirname(os.path.abspath(__file__))
    subprocess.run(
        ["python", "seller_hub_view.py", "--status", "active", "--save", "--all-pages"],
        cwd=hq_dir, check=False,
    )
    print("=== snapshot 取得完了 ===\n")


def load_sheet_item_ids(gc) -> set[str]:
    """統合Hight/Low の B 列 ItemID 集合."""
    ids = set()
    for sid in SHEET_IDS:
        sh = gc.open_by_key(sid)
        ws = sh.get_worksheet_by_id(SHEET_GID)
        for r in ws.get_all_values()[1:]:
            iid = r[1].strip() if len(r) > 1 else ""
            if iid and iid.isdigit():
                ids.add(iid)
    return ids


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-fresh-snapshot", action="store_true",
                        help="新 snapshot 取得を skip し最新の既存 snapshot を使う")
    args = parser.parse_args()

    if not args.no_fresh_snapshot:
        take_fresh_snapshot()

    # 最新 snapshot
    snaps = sorted(glob.glob(os.path.join(SNAPSHOT_DIR, "snapshot_active_all_*.csv")))
    if not snaps:
        print("[ERROR] snapshot が見つかりません。--fresh-snapshot で取得してください")
        return 1
    snap = snaps[-1]
    print(f"📂 snapshot: {os.path.basename(snap)}")

    # categorize 共有関数
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from seller_hub_tier import categorize_by_keyword

    with open(snap, "r", encoding="utf-8-sig", newline="") as f:
        rows = [r for r in csv.DictReader(f)
                if int(r.get("quantity_available", "0") or 0) >= 1
                and r.get("listing_site", "") == "US"]
    print(f"   US/qty>=1: {len(rows)} 件")

    # スプシ ItemID 集合
    import gspread
    from google.oauth2.service_account import Credentials
    creds = Credentials.from_service_account_file(
        CREDS_PATH, scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    gc = gspread.authorize(creds)
    sheet_ids = load_sheet_item_ids(gc)
    print(f"   スプシ B列 ItemID: {len(sheet_ids)} 件")

    # 出力
    os.makedirs(DESKTOP_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = os.path.join(DESKTOP_DIR, f"relist_us_qty1_sku_{ts}.csv")
    in_count, out_count = 0, 0
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["category", "item_id", "sku", "title", "price_usd",
                        "views", "watchers", "quantity_available",
                        "listed_date", "listing_site", "in_spreadsheet"],
            quoting=csv.QUOTE_NONNUMERIC, extrasaction="ignore",
        )
        w.writeheader()
        for t in rows:
            t["category"] = categorize_by_keyword(t.get("title", ""))
            in_sh = t["item_id"] in sheet_ids
            t["in_spreadsheet"] = "YES" if in_sh else "NO (orphan)"
            if in_sh:
                in_count += 1
            else:
                out_count += 1
            w.writerow(t)
    print(f"\n📋 出力: {out}")
    print(f"   YES (スプシ在): {in_count}")
    print(f"   NO (orphan):    {out_count}")
    try:
        os.startfile(out)
        print(f"   → Excel 自動 open")
    except Exception as e:
        print(f"   [WARN] auto-open 失敗: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
