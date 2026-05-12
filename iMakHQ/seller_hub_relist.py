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


# ============================================================================
# OLD listing scrape (5/12 追加: ビフォーアフター CSV 用)
# ============================================================================
def save_old_state_csv(item_ids: list[str], results: list[dict]) -> str:
    """B 列空欄化 直前に eBay 公開ページを scrape して旧 listing 全情報を保存.

    NEW state (= Add CSV) と pair して relist_diff_*.csv を生成するための土台。
    Selenium 利用、1 listing 約 5-10 秒、N 件で N*10 秒。
    """
    import json
    sys.path.insert(0, os.path.normpath(os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "iMakeBayAPI")))
    try:
        from ebay_listing_scraper import scrape_listings_batch
    except ImportError as e:
        print(f"[WARN] ebay_listing_scraper import 失敗: {e} → OLD state scrape skip")
        return ""

    # OK のみ scrape (NOT_FOUND は URL 不明)
    ok_results = [r for r in results if r.get("status") == "OK" and r.get("url")]
    urls = [r["url"] for r in ok_results]
    if not urls:
        print("[INFO] OLD state scrape 対象なし")
        return ""

    print(f"\n=== OLD state scrape: {len(urls)} listings (約 {len(urls) * 8} 秒) ===")

    def _progress(i, total, r):
        title_short = (r.get("title") or "")[:50]
        err = r.get("scrape_error", "")
        marker = "✗" if err else "✓"
        print(f"  [{i}/{total}] {marker} {r.get('item_id', '?')} {title_short}{' err=' + err if err else ''}")

    scraped = scrape_listings_batch(urls, wait_seconds=5, progress_callback=_progress)

    # CSV 保存
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = os.path.join(OUTPUT_DIR, f"relist_old_state_{ts}.csv")
    fields = ["item_id", "url", "status", "title", "price_usd", "price_raw",
              "quantity", "condition", "specifics_json", "scrape_error"]
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields, quoting=csv.QUOTE_NONNUMERIC,
                           extrasaction="ignore")
        w.writeheader()
        for r in scraped:
            row = dict(r)
            row["specifics_json"] = json.dumps(r.get("specifics", {}),
                                                ensure_ascii=False)
            w.writerow(row)
    print(f"💾 OLD state CSV: {out_path}")
    return out_path


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


def auto_extract_targets(category: str, max_listings: int = 0) -> list[str]:
    """最新 snapshot から指定カテゴリの改善対象 item_id を抽出 (US-only).

    条件: 14日超 + views=0 + watchers=0 + qty>=1 + listing_site=US + categorize 一致

    max_listings: 0 or None = キャップなし (スプシ在 filter 後に適用するため、
                  ここでは制限しないのが推奨)。
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
        "montbell": "Montbell",
        "other": "Other",
    }
    target_cat = CAT_MAP.get(category.lower(), category)
    filtered = [t for t in targets if categorize_by_keyword(t.get("title", "")) == target_cat]

    # max_listings 上限 (caller 側で再制限可、0/None でキャップなし)
    if max_listings and max_listings > 0:
        filtered = filtered[:max_listings]
    return [t["item_id"] for t in filtered if t.get("item_id")]


def find_and_update_row(ws, item_id: str, dry_run: bool = True) -> dict | None:
    """スプシ ws で item_id を B 列で検索、見つかれば B 列のみ空欄化.

    旧 ItemID は mapping CSV (caller 側で管理) に保存、スプシには退避列を作らない。

    Returns:
        dict (row_idx, old_item_id, row_data) if found, None if not found
    """
    rows = ws.get_all_values()
    return _find_in_rows(rows, item_id)


def _find_in_rows(rows: list[list[str]], item_id: str) -> dict | None:
    """get_all_values 済の rows 配列から item_id を検索 (API 不要、in-memory).

    5/12 429 rate limit 対策: 各 spreadsheet を 1 回だけ読込 → 全 item_id を in-memory 照合.
    """
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
            return {"row_idx": idx, "old_item_id": item_id, "row_data": row_data}
    return None


def _gspread_with_retry(func, max_retries: int = 4, base_delay: float = 30.0):
    """gspread call を 429 backoff retry でラップ.

    429 Quota exceeded は分単位 reset なので、base_delay は 30s 推奨.
    """
    import time
    last_err = None
    for attempt in range(max_retries + 1):
        try:
            return func()
        except Exception as e:
            err_str = str(e)
            last_err = e
            if "429" not in err_str and "Quota exceeded" not in err_str:
                raise  # 非 429 は即 raise
            if attempt < max_retries:
                wait = base_delay * (1 + attempt * 0.5)  # 30, 45, 60, 75 秒
                print(f"  [429] {err_str[:80]} → {wait:.0f}s 待機して retry ({attempt+1}/{max_retries})")
                time.sleep(wait)
    raise last_err


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
    parser.add_argument("--max-listings", type=int, default=10,
                        help="1 回処理上限 (default: 10, 5/12 429 rate limit 対策で 50→10 に縮小)")
    parser.add_argument("--execute", action="store_true",
                        help="本書込実行 (default: dry-run)")
    parser.add_argument("--skip-end-csv", action="store_true",
                        help="End CSV 生成を skip (Step 1 のみ実行)")
    parser.add_argument("--skip-scrape", action="store_true",
                        help="OLD state scrape を skip (--execute 時のみ scrape する)")
    args = parser.parse_args()

    if not args.sample and not args.category:
        print("[ERROR] --sample <path> or --category <name> のいずれか必須")
        return 1

    dry_run = not args.execute

    # サンプル item_id 取得 (--sample CSV or --category 自動抽出)
    # max_listings はスプシ在 filter 後 (main 内) で適用するため、ここでは 0 で全件取得
    if args.sample:
        item_ids = load_sample_item_ids(args.sample)
        print(f"📂 sample: {args.sample}")
    else:
        item_ids = auto_extract_targets(args.category, max_listings=0)
        print(f"📂 自動抽出: category={args.category} (snapshot 一致全件、max={args.max_listings} はスプシ在 filter 後に適用)")
    print(f"   候補 item_id: {len(item_ids)} 件")
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

    # 1. 各 spreadsheet の全行を 1 回だけ読込 (429 rate limit 対策)
    #    旧: get_all_values を item_id 毎 × 2 sheet = 48 reads → 429
    #    新: get_all_values を sheet 毎 1 回のみ = 2 reads
    sheet_caches: dict[str, dict] = {}  # sheet_id → {"rows": [...], "ws": ws, "cfg": sheet_cfg}
    for sheet_cfg in SHEETS:
        try:
            sh = _gspread_with_retry(lambda c=sheet_cfg: gc.open_by_key(c["id"]))
            ws = _gspread_with_retry(lambda s=sh, c=sheet_cfg: s.get_worksheet_by_id(c["gid"]))
            rows = _gspread_with_retry(lambda w=ws: w.get_all_values())
            sheet_caches[sheet_cfg["id"]] = {"rows": rows, "ws": ws, "cfg": sheet_cfg}
            print(f"  📥 {sheet_cfg['label']}: {len(rows)} 行キャッシュ")
        except Exception as e:
            print(f"  [ERROR] sheet {sheet_cfg['label']} 取得失敗 (retry 後): {e}")
            sheet_caches[sheet_cfg["id"]] = None

    # 2. スプシ B 列に存在する item_id を抽出 (5/12 ユーザー判断: スプシ未登録は除外)
    sheet_item_ids: set[str] = set()
    for cache in sheet_caches.values():
        if cache is None:
            continue
        for row in cache["rows"][1:]:  # skip header
            iid = row[COL_ITEM_ID - 1].strip() if len(row) > COL_ITEM_ID - 1 else ""
            if iid and iid.isdigit():
                sheet_item_ids.add(iid)
    before_filter = len(item_ids)
    item_ids = [iid for iid in item_ids if iid in sheet_item_ids]
    skipped_orphan = before_filter - len(item_ids)
    if skipped_orphan:
        print(f"  🚫 スプシ未登録 (在庫持ち等) を除外: {skipped_orphan} 件")
    # max_listings 適用 (filter 後)
    if args.max_listings and args.max_listings > 0:
        item_ids = item_ids[:args.max_listings]
    print(f"   処理対象: {len(item_ids)} 件 (max-listings={args.max_listings} 適用後)")
    if not item_ids:
        print("[INFO] スプシ在 filter 後 0 件、終了")
        return 0

    # 3. 検索 phase (in-memory、API 不要)
    results = []
    for iid in item_ids:
        found = False
        for sheet_cfg in SHEETS:
            cache = sheet_caches.get(sheet_cfg["id"])
            if cache is None:
                continue
            result = _find_in_rows(cache["rows"], iid)
            if result:
                results.append({
                    "item_id": iid,
                    "sheet": sheet_cfg["label"],
                    "sheet_id": sheet_cfg["id"],
                    "gid": sheet_cfg["gid"],
                    "row_idx": result["row_idx"],
                    "status": "OK",
                    **result.get("row_data", {}),
                })
                found = True
                break
        if not found:
            results.append({"item_id": iid, "sheet": "-", "row_idx": None, "status": "NOT_FOUND"})

    # 3. OLD state scrape (execute かつ skip-scrape なしの時のみ、空欄化前に保存)
    if not dry_run and not args.skip_scrape:
        save_old_state_csv(item_ids, results)

    # 4. B 列空欄化 (execute 時のみ実書込、retry 付き)
    if not dry_run:
        for r in results:
            if r["status"] != "OK":
                continue
            cache = sheet_caches.get(r["sheet_id"])
            if not cache:
                r["status"] = "WRITE_FAILED"
                continue
            ws = cache["ws"]
            try:
                _gspread_with_retry(
                    lambda w=ws, idx=r["row_idx"]: w.update_acell(f"B{idx}", "")
                )
            except Exception as e:
                print(f"  [WARN] {r['item_id']} B列空欄化失敗 (retry 後): {e}")
                r["status"] = "WRITE_FAILED"

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
