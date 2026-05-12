"""seller_hub_relist - View=0 死蔵 listing 取り下げ再出品 統合ツール (HQ 担当).

5/12 ユーザー判断: 案 B (Add 先行 → 即 End)、in-place 方式。

役割:
  Step 1: スプシ B 列空欄化 + AI 列に旧 ItemID 退避
  Step 2: 旧 ItemID から End CSV 生成

Revise くん不要 (役割不一致のため取下げ)。
Add CSV 生成は出品くん各カテゴリ program に任せる (既存挙動)。

使い方:
  python seller_hub_relist.py --sample <csv_path>           # dry-run (default)
  python seller_hub_relist.py --sample <csv_path> --execute # 本書込
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# ============================================================================
# スプシ設定 (5/12 判明、2 スプシで全カテゴリ管理)
# ============================================================================
SHEETS = [
    {
        "id": "19kj8NqWHIGP1ptQDeGePw077hpdl6dNOO-v2J10HCjk",
        "label": "スプシ1 (Porter/TCG/Ichibankuji/UNIQLO UT/Other)",
        "gid": 851100680,
    },
    {
        "id": "1jF9vggbfUCddjneROMO2GGN-jTAPRbq6Qe2cbgr37B0",
        "label": "スプシ2 (G-Shock/Tomica/Reel/フィギュア/グッズ/etc)",
        "gid": 851100680,
    },
]

# 列構成 (両スプシ共通、5/12 確認済)
COL_ITEM_ID = 2   # B 列 (= itemID)
COL_LISTED  = 21  # U 列 (= 出品日時)
# 退避列は廃止 (5/12: AI 列はグリッド外、mapping CSV で管理に変更)

CREDS_PATH = r"c:\dev\iMak\double-hold-421922-7c0d38d3f73d.json"

# ============================================================================
# End CSV (eBay FileExchange Action=EndItem)
# ============================================================================
END_CSV_HEADER = [
    "*Action(SiteID=US|Country=JP|Currency=USD|Version=745|CC=UTF-8)",
    "ItemID",
    "EndCode",
]
END_CODE = "OtherListingError"  # Cassini reset 目的、汎用 code 使用 (NotAvailable は売切専用)
OUTPUT_DIR = r"c:\dev\iMak_data\revise"


def load_sample_item_ids(sample_csv: str) -> list[str]:
    """sample CSV から item_id 一覧を抽出."""
    ids = []
    with open(sample_csv, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            iid = row.get("item_id", "").strip()
            if iid and iid.isdigit():
                ids.append(iid)
    return ids


def auto_extract_targets(category: str, max_listings: int) -> list[str]:
    """最新 snapshot から指定カテゴリの改善対象 item_id を抽出 (US-only).

    条件: 14日超 + views=0 + watchers=0 + qty>=1 + listing_site=US + categorize 一致
    """
    import sys
    import glob
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from seller_hub_tier import filter_improvement_targets, categorize_by_keyword

    # 最新 snapshot 自動選択
    snapshots = sorted(glob.glob(r"C:\dev\iMak_data\seller_hub\snapshot_active_all_*.csv"))
    if not snapshots:
        print("[ERROR] snapshot CSV が見つかりません")
        return []
    snap_path = snapshots[-1]
    print(f"📂 snapshot: {os.path.basename(snap_path)}")

    with open(snap_path, "r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    # filter: 14日超 + views=0 + watchers=0 + qty>=1 + US
    targets = filter_improvement_targets(
        rows, min_days=14, max_views_for_zero_watch=5, site="US",
    )
    targets = [t for t in targets
               if int(t.get("views", "0") or 0) == 0
               and int(t.get("watchers", "0") or 0) == 0
               and int(t.get("quantity_available", "0") or 0) >= 1]

    # category map: CLI category → categorize_by_keyword の返り値
    CAT_MAP = {
        "tshirt": "UNIQLO UT",
        "porter": "Porter",
        "gshock": "G-Shock",
        "tcg": "PSA10 TCG",
        "reel": "Reel",
        "ichibankuji": "Ichiban Kuji",
        "tomica": "Tomica",
        "montbell": "Montbell",  # categorize にないが今後追加可
        "other": "Other",
    }
    target_cat = CAT_MAP.get(category.lower(), category)
    filtered = [t for t in targets if categorize_by_keyword(t.get("title", "")) == target_cat]

    # max_listings 上限
    filtered = filtered[:max_listings]
    return [t["item_id"] for t in filtered if t.get("item_id")]


def find_and_update_row(ws, item_id: str, dry_run: bool = True) -> dict | None:
    """スプシ ws で item_id を B 列で検索、見つかれば B 列のみ空欄化.

    旧 ItemID は mapping CSV (caller 側で管理) に保存、スプシには退避列を作らない。

    Returns:
        dict (row_idx, old_item_id, row_data) if found, None if not found
    """
    rows = ws.get_all_values()
    for idx, row in enumerate(rows[1:], start=2):  # row 1 は header
        if len(row) > COL_ITEM_ID - 1 and row[COL_ITEM_ID - 1].strip() == item_id:
            row_data = {
                "url": row[0] if len(row) > 0 else "",
                "title": row[2] if len(row) > 2 else "",
                "sold_out": row[3] if len(row) > 3 else "",
                "condition": row[4] if len(row) > 4 else "",
                "price_jpy": row[5] if len(row) > 5 else "",
                "photo_url": row[6] if len(row) > 6 else "",
                "category": row[17] if len(row) > 17 else "",
                "listed_date": row[20] if len(row) > 20 else "",
            }
            if not dry_run:
                # B 列空欄化のみ (退避列なし、mapping CSV で管理)
                ws.update_acell(f"B{idx}", "")
            return {"row_idx": idx, "old_item_id": item_id, "row_data": row_data}
    return None


def save_mapping_csv(results: list[dict]) -> str:
    """旧 ItemID → スプシ位置 mapping を CSV 保存."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = os.path.join(OUTPUT_DIR, f"relist_mapping_{ts}.csv")
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, quoting=csv.QUOTE_NONNUMERIC)
        w.writerow(["old_item_id", "sheet", "row_idx", "status", "timestamp"])
        for r in results:
            w.writerow([
                r["item_id"], r["sheet"], r.get("row_idx", ""),
                r["status"], datetime.now().isoformat(timespec="seconds"),
            ])
    return out_path


def save_status_csv(results: list[dict]) -> str:
    """成果確認 CSV: 旧 listing 詳細 + B 列空欄化 status + 次のステップ案内."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = os.path.join(OUTPUT_DIR, f"relist_status_{ts}.csv")
    fields = [
        "old_item_id", "sheet", "row_idx", "status",
        "url", "title", "price_jpy", "category",
        "listed_date", "sold_out", "condition",
        "photo_url", "next_action",
    ]
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields, quoting=csv.QUOTE_NONNUMERIC,
                           extrasaction="ignore")
        w.writeheader()
        for r in results:
            r_out = dict(r)
            r_out["old_item_id"] = r["item_id"]
            r_out["next_action"] = (
                "出品くん 該当カテゴリボタン押下 → Add CSV 生成 → eBay upload"
                if r["status"] == "OK" else "スプシ位置不明、手動確認要"
            )
            w.writerow(r_out)
    return out_path


def generate_end_csv(item_ids: list[str]) -> str:
    """旧 ItemID 一覧から End CSV を生成、出力 path を返す."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = os.path.join(OUTPUT_DIR, f"relist_end_{ts}.csv")
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, quoting=csv.QUOTE_NONNUMERIC)
        w.writerow(END_CSV_HEADER)
        for iid in item_ids:
            w.writerow(["EndItem", iid, END_CODE])
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", help="改善対象 sample CSV path (省略時は --category から自動抽出)")
    parser.add_argument("--category", help="カテゴリ指定で snapshot から自動抽出 (tshirt/porter/gshock/tcg/reel/ichibankuji/tomica/montbell/other)")
    parser.add_argument("--max-listings", type=int, default=50, help="1 回処理上限 (default: 50)")
    parser.add_argument("--execute", action="store_true",
                        help="本書込実行 (default: dry-run)")
    parser.add_argument("--skip-end-csv", action="store_true",
                        help="End CSV 生成を skip (Step 1 のみ実行)")
    args = parser.parse_args()

    if not args.sample and not args.category:
        print("[ERROR] --sample <path> or --category <name> のいずれか必須")
        return 1

    dry_run = not args.execute

    # サンプル item_id 取得 (--sample CSV or --category 自動抽出)
    if args.sample:
        item_ids = load_sample_item_ids(args.sample)
        print(f"📂 sample: {args.sample}")
    else:
        item_ids = auto_extract_targets(args.category, args.max_listings)
        print(f"📂 自動抽出: category={args.category}, max={args.max_listings}")
    print(f"   対象 item_id: {len(item_ids)} 件")
    print(f"   mode: {'DRY-RUN' if dry_run else 'EXECUTE'}")
    print()

    if not item_ids:
        print("[INFO] 対象 0 件、終了")
        return 0

    # gspread 接続
    import gspread
    from google.oauth2.service_account import Credentials
    creds = Credentials.from_service_account_file(
        CREDS_PATH, scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    gc = gspread.authorize(creds)

    # 各 item_id を 両スプシで検索
    results = []
    for iid in item_ids:
        found = False
        for sheet_cfg in SHEETS:
            try:
                sh = gc.open_by_key(sheet_cfg["id"])
                ws = sh.get_worksheet_by_id(sheet_cfg["gid"])
                result = find_and_update_row(ws, iid, dry_run=dry_run)
                if result:
                    results.append({
                        "item_id": iid,
                        "sheet": sheet_cfg["label"],
                        "row_idx": result["row_idx"],
                        "status": "OK",
                        **result.get("row_data", {}),
                    })
                    found = True
                    break
            except Exception as e:
                print(f"  [WARN] sheet {sheet_cfg['label']} アクセス失敗: {e}")
        if not found:
            results.append({"item_id": iid, "sheet": "-", "row_idx": None, "status": "NOT_FOUND"})

    # 結果サマリー
    print("=== Step 1: スプシ B 列空欄化 結果 ===")
    ok_count = sum(1 for r in results if r["status"] == "OK")
    print(f"  OK:        {ok_count} / {len(item_ids)} 件")
    print(f"  NOT_FOUND: {len(item_ids) - ok_count} 件")
    print()
    for r in results:
        if r["status"] == "OK":
            print(f"  ✓ {r['item_id']} → {r['sheet']} 行 {r['row_idx']}")
        else:
            print(f"  ✗ {r['item_id']} → どのスプシにも未発見")
    print()

    # mapping CSV + status CSV 出力 (dry-run でも生成)
    if results:
        mapping_path = save_mapping_csv(results)
        print(f"💾 mapping CSV: {mapping_path}")
        status_path = save_status_csv(results)
        print(f"📊 成果確認 CSV: {status_path}")
        print()

    # End CSV 生成 (Step 2)
    if not args.skip_end_csv and ok_count > 0:
        ok_ids = [r["item_id"] for r in results if r["status"] == "OK"]
        if dry_run:
            print(f"=== Step 2: End CSV 生成 (dry-run、出力なし) ===")
            print(f"  生成予定 ItemID: {len(ok_ids)} 件")
            print(f"  EndCode: {END_CODE}")
        else:
            end_csv_path = generate_end_csv(ok_ids)
            print(f"=== Step 2: End CSV 生成 ===")
            print(f"  ✅ 出力: {end_csv_path}")
            print(f"  件数: {len(ok_ids)}")

    print()
    if dry_run:
        print("[DRY-RUN] 実書込なし。 --execute で本実行")
    else:
        print("[EXECUTE] 完了")
    return 0 if ok_count > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
