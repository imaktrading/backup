"""seller_hub_writeback - 再出品 Add CSV upload 後の新 ItemID をスプシ B 列に書込.

5/12 ユーザー判断: 数十件規模の再出品で手動 ItemID 貼付は不可 → 自動化必須。

役割:
  1. eBay Active Listings Report (DL CSV) を読込
  2. relist_mapping_*.csv (最新) と Custom Label (SKU = URL末尾12文字) で照合
  3. 新 ItemID をスプシ B 列に書込 (gspread update_acell)
  4. relist_old_state_*.csv (再出品 scrape 結果) + iMakHQ/csv_output/*_upload_*.csv (NEW)
     を pair して relist_diff_*.csv をデスクトップに生成 + os.startfile auto-open

使い方 (CLI):
  python seller_hub_writeback.py --active-report <path> --execute
  python seller_hub_writeback.py --active-report <path>  # dry-run

使い方 (GUI):
  control_panel.py「再出品結果反映」ボタン → file dialog → ここを呼ぶ
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# パス定数
REVISE_DIR = r"c:\dev\iMak_data\revise"
ACTIVE_REPORTS_DIR = r"c:\dev\iMak_data\seller_hub\active_reports"
DESKTOP_DIR = r"C:\Users\imax2\OneDrive\デスクトップ"
ADD_CSV_DIR = r"c:\dev\iMak\iMakHQ\csv_output"
CREDS_PATH = r"c:\dev\iMak\double-hold-421922-7c0d38d3f73d.json"

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


def sku_from_url(url: str) -> str:
    """URL末尾12文字を SKU として抽出 (listing_common.extract_sku_from_url と同規約)."""
    if not url:
        return ""
    cleaned = url.split("?")[0].split("#")[0].rstrip("/")
    return cleaned[-12:].lstrip("/")


# ============================================================================
# CSV 読込
# ============================================================================
def read_active_report(path: str) -> dict[str, dict]:
    """Active Listings Report を SKU → 全 row dict にマップ.

    `Custom label (SKU)` 列が空の旧 listing は skip (新出品 listing のみ対象)。
    """
    out: dict[str, dict] = {}
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            sku = (row.get("Custom label (SKU)") or "").strip()
            if not sku:
                continue
            # 新出品で URL末尾12文字 SKU が入ってる行のみ対象 (旧運用 "zaiko" 等は無視)
            # → 全部入れて caller 側で照合判定 (誤判定で取りこぼすより取り過ぎて照合 miss にする方が安全)
            out[sku] = row
    return out


def read_mapping_csv(path: str) -> list[dict]:
    """relist_mapping_*.csv 読込."""
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def read_old_state_csv(path: str) -> dict[str, dict]:
    """relist_old_state_*.csv を item_id → row dict にマップ."""
    if not path or not os.path.exists(path):
        return {}
    out: dict[str, dict] = {}
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            iid = (row.get("item_id") or "").strip()
            if iid:
                # specifics_json を dict に戻す
                try:
                    row["specifics"] = json.loads(row.get("specifics_json", "{}"))
                except Exception:
                    row["specifics"] = {}
                out[iid] = row
    return out


def read_recent_add_csvs(within_hours: int = 24) -> dict[str, dict]:
    """直近 N 時間に生成された Add CSV を全部読んで CustomLabel(SKU) → row dict にマップ.

    複数カテゴリの Add CSV を横断統合。SKU 衝突は最新優先 (mtime 順)。
    """
    out: dict[str, dict] = {}
    cutoff = datetime.now() - timedelta(hours=within_hours)
    csvs = []
    for pat in ("*_upload_*.csv",):
        for p in glob.glob(os.path.join(ADD_CSV_DIR, pat)):
            try:
                mt = datetime.fromtimestamp(os.path.getmtime(p))
                if mt >= cutoff:
                    csvs.append((mt, p))
            except OSError:
                continue
    csvs.sort()  # mtime 昇順 (新しいのが後勝ち)
    for _, p in csvs:
        try:
            with open(p, "r", encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    sku = (row.get("CustomLabel") or "").strip()
                    if sku:
                        row["_source_csv"] = os.path.basename(p)
                        out[sku] = row
        except Exception as e:
            print(f"  [WARN] {os.path.basename(p)} 読込失敗: {e}")
    return out


def latest_file(pattern: str, base_dir: str) -> str:
    """base_dir 配下で pattern にマッチする最新 file path を返す (なければ空文字)."""
    matches = sorted(glob.glob(os.path.join(base_dir, pattern)))
    return matches[-1] if matches else ""


# ============================================================================
# Writeback core
# ============================================================================
def process_writeback(active_report_path: str, mapping_path: str = "",
                       old_state_path: str = "",
                       execute: bool = False) -> dict:
    """メイン処理.

    Returns:
        {
            "writeback_log_csv": <path>,
            "diff_csv": <path>,
            "summary": {"ok": N, "not_found": M, "not_yet_listed": K, "errors": L},
        }
    """
    # 入力 CSV ロード
    active_map = read_active_report(active_report_path)
    print(f"📂 Active Report: {os.path.basename(active_report_path)} → {len(active_map)} SKU 行")

    if not mapping_path:
        mapping_path = latest_file("relist_mapping_*.csv", REVISE_DIR)
    if not mapping_path or not os.path.exists(mapping_path):
        print("[ERROR] mapping CSV が見つかりません (--mapping 指定 or 再出品ボタンを先に押す)")
        return {"error": "no_mapping_csv"}
    mapping_rows = read_mapping_csv(mapping_path)
    print(f"📂 mapping CSV: {os.path.basename(mapping_path)} → {len(mapping_rows)} 行")

    if not old_state_path:
        old_state_path = latest_file("relist_old_state_*.csv", REVISE_DIR)
    old_state = read_old_state_csv(old_state_path) if old_state_path else {}
    if old_state:
        print(f"📂 OLD state CSV: {os.path.basename(old_state_path)} → {len(old_state)} 件")
    else:
        print("[INFO] OLD state CSV なし (Item Specifics 比較なしで進行)")

    add_csv_map = read_recent_add_csvs(within_hours=48)
    if add_csv_map:
        print(f"📂 直近 Add CSV (48h): {len(add_csv_map)} SKU 行")

    # gspread 接続 (execute 時のみ実書込)
    gc = None
    if execute:
        import gspread
        from google.oauth2.service_account import Credentials
        creds = Credentials.from_service_account_file(
            CREDS_PATH, scopes=["https://www.googleapis.com/auth/spreadsheets"],
        )
        gc = gspread.authorize(creds)

    sheet_lookup = {s["id"]: s for s in SHEETS}
    # mapping CSV の "sheet" 列は label 文字列なので label → cfg 逆引きも作る
    label_lookup = {s["label"]: s for s in SHEETS}

    # 結果蓄積
    writeback_results: list[dict] = []
    summary = {"ok": 0, "not_found": 0, "not_yet_listed": 0, "errors": 0,
               "skipped_already_filled": 0}

    for m in mapping_rows:
        old_item_id = (m.get("old_item_id") or "").strip()
        sheet_label = (m.get("sheet") or "").strip()
        row_idx_str = (m.get("row_idx") or "").strip()
        status = (m.get("status") or "").strip()
        if status != "OK":
            summary["not_found"] += 1
            writeback_results.append({
                "old_item_id": old_item_id, "new_item_id": "", "sku": "",
                "sheet": sheet_label, "row_idx": row_idx_str,
                "writeback_status": "skipped_mapping_not_ok",
            })
            continue

        # OLD state から URL 取得 → SKU 算出
        os_row = old_state.get(old_item_id) or {}
        url = os_row.get("url", "")
        sku = sku_from_url(url)

        # OLD state がない場合は mapping CSV から URL を推測 (旧 mapping にも url なし、status CSV にあり)
        # → 当面 OLD state なしは sku 取れずスキップ
        if not sku:
            summary["errors"] += 1
            writeback_results.append({
                "old_item_id": old_item_id, "new_item_id": "", "sku": "",
                "sheet": sheet_label, "row_idx": row_idx_str,
                "writeback_status": "no_url_for_sku",
            })
            continue

        # Active Report から新 ItemID 検索
        new_row = active_map.get(sku)
        if not new_row:
            summary["not_yet_listed"] += 1
            writeback_results.append({
                "old_item_id": old_item_id, "new_item_id": "", "sku": sku,
                "sheet": sheet_label, "row_idx": row_idx_str,
                "writeback_status": "not_in_active_report (反映待ち or upload失敗)",
            })
            continue

        new_item_id = (new_row.get("Item number") or "").strip()
        if not new_item_id:
            summary["errors"] += 1
            writeback_results.append({
                "old_item_id": old_item_id, "new_item_id": "", "sku": sku,
                "sheet": sheet_label, "row_idx": row_idx_str,
                "writeback_status": "active_report_item_id_blank",
            })
            continue

        # スプシ書込 (execute 時のみ)
        sheet_cfg = label_lookup.get(sheet_label)
        if not sheet_cfg:
            summary["errors"] += 1
            writeback_results.append({
                "old_item_id": old_item_id, "new_item_id": new_item_id, "sku": sku,
                "sheet": sheet_label, "row_idx": row_idx_str,
                "writeback_status": "unknown_sheet_label",
            })
            continue

        if execute:
            try:
                sh = gc.open_by_key(sheet_cfg["id"])
                ws = sh.get_worksheet_by_id(sheet_cfg["gid"])
                # B列既存値チェック (二重書込防止)
                current_b = ws.acell(f"B{row_idx_str}").value or ""
                if current_b.strip():
                    if current_b.strip() == new_item_id:
                        summary["skipped_already_filled"] += 1
                        writeback_results.append({
                            "old_item_id": old_item_id, "new_item_id": new_item_id,
                            "sku": sku, "sheet": sheet_label, "row_idx": row_idx_str,
                            "writeback_status": "already_filled_same_id",
                        })
                        continue
                    else:
                        summary["errors"] += 1
                        writeback_results.append({
                            "old_item_id": old_item_id, "new_item_id": new_item_id,
                            "sku": sku, "sheet": sheet_label, "row_idx": row_idx_str,
                            "writeback_status": f"B_already_has_different_id:{current_b}",
                        })
                        continue
                ws.update_acell(f"B{row_idx_str}", new_item_id)
                summary["ok"] += 1
                writeback_results.append({
                    "old_item_id": old_item_id, "new_item_id": new_item_id, "sku": sku,
                    "sheet": sheet_label, "row_idx": row_idx_str,
                    "writeback_status": "OK",
                })
            except Exception as e:
                summary["errors"] += 1
                writeback_results.append({
                    "old_item_id": old_item_id, "new_item_id": new_item_id, "sku": sku,
                    "sheet": sheet_label, "row_idx": row_idx_str,
                    "writeback_status": f"gspread_error:{e}",
                })
        else:
            summary["ok"] += 1  # dry-run でも OK 換算
            writeback_results.append({
                "old_item_id": old_item_id, "new_item_id": new_item_id, "sku": sku,
                "sheet": sheet_label, "row_idx": row_idx_str,
                "writeback_status": "DRY_RUN_WOULD_WRITE",
            })

    # writeback log CSV 出力
    os.makedirs(REVISE_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = os.path.join(REVISE_DIR, f"relist_writeback_{ts}.csv")
    with open(log_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=[
            "old_item_id", "new_item_id", "sku", "sheet", "row_idx",
            "writeback_status",
        ], quoting=csv.QUOTE_NONNUMERIC, extrasaction="ignore")
        w.writeheader()
        w.writerows(writeback_results)

    # diff CSV 生成 (OLD/NEW pair、Item Specifics 全列)
    diff_path = generate_diff_csv(
        writeback_results, old_state, add_csv_map, active_map, ts,
    )

    # Active Report をアーカイブ保存
    os.makedirs(ACTIVE_REPORTS_DIR, exist_ok=True)
    archive_name = f"{ts}_{os.path.basename(active_report_path)}"
    archive_path = os.path.join(ACTIVE_REPORTS_DIR, archive_name)
    try:
        shutil.copy2(active_report_path, archive_path)
    except Exception as e:
        print(f"  [WARN] Active Report アーカイブ失敗: {e}")

    return {
        "writeback_log_csv": log_path,
        "diff_csv": diff_path,
        "summary": summary,
        "mapping_csv": mapping_path,
        "old_state_csv": old_state_path,
        "active_report_archive": archive_path,
    }


# ============================================================================
# Diff CSV 生成 (OLD/NEW 2 行 pair 形式、relist_diff_*.csv 互換)
# ============================================================================
def generate_diff_csv(writeback_results: list[dict],
                       old_state: dict,
                       add_csv_map: dict,
                       active_map: dict,
                       ts: str) -> str:
    """OLD/NEW pair 形式の diff CSV をデスクトップに生成.

    各 mapping entry に対して:
      - OLD 行: old_state CSV の値 (URL/Title/Price/Quantity/Item Specifics)
      - NEW 行: Add CSV (recent) の値 + Active Report の新 ItemID
    """
    if not writeback_results:
        return ""

    # 列構成: 共通列 + 動的 Item Specifics 列
    base_cols = ["marker", "item_id", "sku", "writeback_status",
                 "title", "price_usd", "quantity", "condition", "url"]
    spec_keys: set[str] = set()
    for r in writeback_results:
        old_iid = r.get("old_item_id", "")
        new_iid = r.get("new_item_id", "")
        os_row = old_state.get(old_iid, {})
        for k in (os_row.get("specifics") or {}).keys():
            spec_keys.add(k)
        sku = r.get("sku", "")
        add_row = add_csv_map.get(sku, {})
        for k in add_row.keys():
            if k.startswith("C:") and add_row[k]:
                spec_keys.add(k[2:])  # "C:Brand" → "Brand"
    spec_cols = sorted(spec_keys)
    all_cols = base_cols + spec_cols

    os.makedirs(DESKTOP_DIR, exist_ok=True)
    out_path = os.path.join(DESKTOP_DIR, f"relist_diff_{ts}.csv")

    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=all_cols, quoting=csv.QUOTE_NONNUMERIC,
                           extrasaction="ignore")
        w.writeheader()
        for r in writeback_results:
            old_iid = r.get("old_item_id", "")
            new_iid = r.get("new_item_id", "")
            sku = r.get("sku", "")
            os_row = old_state.get(old_iid, {})
            add_row = add_csv_map.get(sku, {})
            active_row = active_map.get(sku, {})

            # OLD 行
            old_row_dict = {
                "marker": "OLD",
                "item_id": old_iid,
                "sku": sku,
                "writeback_status": r.get("writeback_status", ""),
                "title": os_row.get("title", ""),
                "price_usd": os_row.get("price_usd", ""),
                "quantity": os_row.get("quantity", ""),
                "condition": os_row.get("condition", ""),
                "url": os_row.get("url", ""),
            }
            for k in spec_cols:
                old_row_dict[k] = (os_row.get("specifics") or {}).get(k, "")
            w.writerow(old_row_dict)

            # NEW 行
            new_row_dict = {
                "marker": "NEW",
                "item_id": new_iid,
                "sku": sku,
                "writeback_status": r.get("writeback_status", ""),
                "title": add_row.get("*Title", "") or active_row.get("Title", ""),
                "price_usd": add_row.get("*StartPrice", "") or active_row.get("Start price", ""),
                "quantity": add_row.get("*Quantity", "") or active_row.get("Available quantity", ""),
                "condition": add_row.get("ConditionID", ""),
                "url": f"https://www.ebay.com/itm/{new_iid}" if new_iid else "",
            }
            for k in spec_cols:
                new_row_dict[k] = add_row.get(f"C:{k}", "")
            w.writerow(new_row_dict)

    return out_path


# ============================================================================
# CLI
# ============================================================================
def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--active-report", required=True,
                        help="eBay Active Listings Report CSV path")
    parser.add_argument("--mapping", default="",
                        help="relist_mapping CSV path (省略時最新 auto-detect)")
    parser.add_argument("--old-state", default="",
                        help="relist_old_state CSV path (省略時最新 auto-detect)")
    parser.add_argument("--execute", action="store_true",
                        help="本書込実行 (default: dry-run)")
    parser.add_argument("--no-open", action="store_true",
                        help="diff CSV の auto-open を skip (test 用)")
    args = parser.parse_args()

    if not os.path.exists(args.active_report):
        print(f"[ERROR] Active Report が見つかりません: {args.active_report}")
        return 1

    print(f"=== seller_hub_writeback 開始 (mode: {'EXECUTE' if args.execute else 'DRY-RUN'}) ===\n")
    result = process_writeback(
        args.active_report, args.mapping, args.old_state,
        execute=args.execute,
    )

    if "error" in result:
        return 1

    print()
    print("=== 結果サマリー ===")
    s = result["summary"]
    print(f"  OK:                       {s['ok']} 件")
    print(f"  not_in_active_report:     {s['not_yet_listed']} 件 (反映待ち or upload 失敗)")
    print(f"  not_found / not_ok:       {s['not_found']} 件")
    print(f"  already_filled (skip):    {s['skipped_already_filled']} 件")
    print(f"  errors:                   {s['errors']} 件")
    print()
    print(f"📊 writeback log: {result['writeback_log_csv']}")
    if result.get("diff_csv"):
        print(f"📋 diff CSV:      {result['diff_csv']}")
    if result.get("active_report_archive"):
        print(f"💾 Active Report archive: {result['active_report_archive']}")

    # auto-open
    if not args.no_open and result.get("diff_csv") and os.path.exists(result["diff_csv"]):
        try:
            os.startfile(result["diff_csv"])
            print(f"\n📂 diff CSV を自動 open しました")
        except Exception as e:
            print(f"  [WARN] auto-open 失敗: {e}")

    if not args.execute:
        print("\n[DRY-RUN] 実書込なし。 --execute で本実行")
    return 0


if __name__ == "__main__":
    sys.exit(main())
