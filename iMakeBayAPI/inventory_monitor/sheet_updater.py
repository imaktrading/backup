"""sheet_updater - SKU シート (Google Sheets) の読込・更新 (独立モジュール).

設計原則:
  - 既存の gspread + サービスアカウント (`double-hold-421922-...json`) を再利用
  - 既存スプシ・タブ構成を一切壊さない (列構成は SKU 詳細シートに準拠)
  - 失敗時は例外送出、main 側でログ + retry 判断

スプシ構造 (SKU 詳細タブ、列 A-L):
  A: 対処要 (TRUE/FALSE chkbox)
  B: 対処済 (TRUE/FALSE chkbox)
  C: 対処日 (YYYY/MM/DD)
  D: listing ID
  E: title
  F: eBay SKU ID
  G: サイズ
  H: 色
  I: 仕入元在庫 (◎ / ✕)
  J: 仕入元価格
  K: eBay 現Qty
  L: 自動CHK日

メインシート構造 (本ファイルが参照):
  A: FLG (1 で除外、それ以外は active)
  D: listing ID
  E: title
  F: 仕入元 URL (uniqlo.com / montbell.com / amazon.co.jp 等)

使用例:
    from sheet_updater import open_sheet, read_main_active_uniqlo_rows, update_sku_rows
    sh = open_sheet()
    rows = read_main_active_uniqlo_rows(sh)
    update_sku_rows(sh, [{...}, {...}])
"""
from __future__ import annotations

import os
import urllib.parse
from datetime import datetime
from typing import Optional

import gspread
from google.oauth2.service_account import Credentials


SPREADSHEET_ID = "101KL6KxMugKqZeSp2W5L2ykTvT0Zwd3RzlfsHgiJsg0"
SKU_TAB_NAME = "SKU詳細"
CREDS_PATH = r"c:\dev\iMak\double-hold-421922-7c0d38d3f73d.json"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# メインシート列マッピング (1-based)
# 実シート (シート1) header: A=FLG, B=title, C=item ID, D=(空), E=ebay URL, F=URL(仕入元), G=CHK date
MAIN_COL_FLG = 1         # A
MAIN_COL_TITLE = 2       # B
MAIN_COL_LISTING_ID = 3  # C
MAIN_COL_URL = 6         # F (仕入元URL)


# ============================================================================
# 認証 / スプシオープン
# ============================================================================
def open_sheet():
    """サービスアカウント認証 → spreadsheet オブジェクト返却."""
    if not os.path.exists(CREDS_PATH):
        raise FileNotFoundError(f"サービスアカウント JSON が見つかりません: {CREDS_PATH}")
    creds = Credentials.from_service_account_file(CREDS_PATH, scopes=SCOPES)
    gc = gspread.authorize(creds)
    return gc.open_by_key(SPREADSHEET_ID)


def get_main_worksheet(sh):
    """メインシート (1番目のシート想定、または 'メイン' / 'main' 名の検索)."""
    for name_candidate in ("メイン", "main", "Main", "Sheet1"):
        try:
            return sh.worksheet(name_candidate)
        except gspread.WorksheetNotFound:
            continue
    # フォールバック: 最初のシート
    return sh.get_worksheet(0)


def get_sku_worksheet(sh):
    """SKU 詳細シート."""
    return sh.worksheet(SKU_TAB_NAME)


# ============================================================================
# メインシート読込
# ============================================================================
def _domain_of(url: str) -> str:
    if not url:
        return ""
    try:
        return urllib.parse.urlparse(url).netloc.lower()
    except Exception:
        return ""


def read_main_active_rows(sh, supplier_filter: str = "all") -> list:
    """メインシートから FLG ≠ 1 (= active) の listing 行を抽出.

    Args:
        supplier_filter: "uniqlo" / "montbell" / "all" (Phase 1 対応仕入元のみ)
    """
    main_ws = get_main_worksheet(sh)
    all_values = main_ws.get_all_values()
    if not all_values:
        return []

    rows = []
    for idx, row in enumerate(all_values[1:], start=2):
        flg = (row[MAIN_COL_FLG - 1] if len(row) >= MAIN_COL_FLG else "").strip()
        if flg == "1":
            continue
        listing_id = (row[MAIN_COL_LISTING_ID - 1] if len(row) >= MAIN_COL_LISTING_ID else "").strip()
        title = (row[MAIN_COL_TITLE - 1] if len(row) >= MAIN_COL_TITLE else "").strip()
        url = (row[MAIN_COL_URL - 1] if len(row) >= MAIN_COL_URL else "").strip()
        domain = _domain_of(url)
        if not listing_id or not url:
            continue

        # supplier 判定
        if "uniqlo.com" in domain:
            supplier = "uniqlo"
        elif "montbell.jp" in domain:
            supplier = "montbell"
        else:
            supplier = "other"

        if supplier_filter != "all" and supplier != supplier_filter:
            continue
        if supplier_filter == "all" and supplier == "other":
            continue  # Phase 1 未対応の仕入元はスキップ
        rows.append({
            "row_index": idx,
            "listing_id": listing_id,
            "title": title,
            "url": url,
            "domain": domain,
            "supplier": supplier,
        })
    return rows


# 後方互換: 既存呼出元のため残す
def read_main_active_uniqlo_rows(sh) -> list:
    """[Deprecated] read_main_active_rows(sh, 'uniqlo') と同等."""
    return read_main_active_rows(sh, supplier_filter="uniqlo")


# ============================================================================
# SKU シート読込 / 書込
# ============================================================================
def read_sku_rows(sh) -> list:
    """SKU 詳細シートの全行 (header 除く) を返す."""
    sku_ws = get_sku_worksheet(sh)
    all_values = sku_ws.get_all_values()
    if len(all_values) < 2:
        return []
    return all_values[1:]


def update_sku_rows(sh, updates: list) -> dict:
    """SKU 詳細シートに update を適用.

    Args:
        updates: [
            {
                "row_index":  6 (1-based シート行、None なら append),
                "listing_id": "357401200653",
                "title":      "マンガキュレーション UT",
                "sku_id":     "MK-UT-S-Black" (空可、scraper 由来は communication_code を使う),
                "size":       "S",
                "color":      "BLACK",
                "supplier_stock_mark": "◎" or "✕",
                "supplier_price":     1500,
                "ebay_qty":           1,
                "auto_check_at":      "2026/04/27 10:00",
                "needs_action":       True / False (A列 update 用),
            },
            ...
        ]

    Returns: {"updated": N, "appended": M}
    """
    if not updates:
        return {"updated": 0, "appended": 0}

    sku_ws = get_sku_worksheet(sh)
    all_values = sku_ws.get_all_values()
    last_row = len(all_values)  # 1-based 行数 = 最終行 index

    # append が必要な件数を事前計算 → grid 拡張 (Range exceeds grid limits 対策)
    append_needed = sum(1 for u in updates if u.get("row_index") is None)
    if append_needed > 0:
        target_total_rows = last_row + append_needed + 50  # +50 はバッファ
        if target_total_rows > sku_ws.row_count:
            sku_ws.add_rows(target_total_rows - sku_ws.row_count)

    # batch_update でまとめて書込 (API quota 節約)
    cell_updates = []
    appended_count = 0
    updated_count = 0

    for u in updates:
        row_idx = u.get("row_index")
        if row_idx is None:
            # append: 末尾の次の行
            last_row += 1
            row_idx = last_row
            appended_count += 1
        else:
            updated_count += 1

        row_values = [
            bool(u.get("needs_action", False)),                  # A: 対処要
            False,                                                # B: 対処済 (新規 update では触らないが、新規 append は False)
            "",                                                   # C: 対処日 (新規 append のみ空)
            str(u.get("listing_id", "")),                         # D
            str(u.get("title", "")),                              # E
            str(u.get("sku_id", "")),                             # F
            str(u.get("size", "")),                               # G
            str(u.get("color", "")),                              # H
            str(u.get("supplier_stock_mark", "")),                # I
            u.get("supplier_price") if u.get("supplier_price") is not None else "",  # J
            u.get("ebay_qty") if u.get("ebay_qty") is not None else "",  # K
            str(u.get("auto_check_at", datetime.now().strftime("%Y/%m/%d %H:%M"))),  # L
        ]

        # 既存行 update 時は B/C 列 (対処済/対処日) を上書きしない (人手判断を尊重)
        if u.get("row_index") is not None:
            existing = all_values[row_idx - 1] if row_idx - 1 < len(all_values) else []
            existing_b = (existing[1] if len(existing) >= 2 else "").strip()
            existing_c = (existing[2] if len(existing) >= 3 else "").strip()
            row_values[1] = existing_b == "TRUE" or existing_b == "True"
            row_values[2] = existing_c

        cell_updates.append({
            "range": f"A{row_idx}:L{row_idx}",
            "values": [row_values],
        })

    sku_ws.batch_update(cell_updates, value_input_option="USER_ENTERED")

    return {"updated": updated_count, "appended": appended_count}


# ============================================================================
# 対処要判定ヘルパー
# ============================================================================
def determine_needs_action(supplier_in_stock: bool, ebay_qty: int) -> bool:
    """対処要フラグ判定:
      - 仕入元 ✕ かつ eBay Qty > 0  → True (在庫切れだが eBay 出品中、停止検討)
      - 仕入元 ◎ かつ eBay Qty = 0  → True (仕入復活、再開検討)
      - それ以外                    → False
    """
    if supplier_in_stock and ebay_qty == 0:
        return True
    if (not supplier_in_stock) and ebay_qty > 0:
        return True
    return False


# ============================================================================
# CLI (動作確認用)
# ============================================================================
if __name__ == "__main__":
    import sys
    print("=== Open spreadsheet ===")
    sh = open_sheet()
    print(f"  title: {sh.title}")

    print("\n=== Main sheet UNIQLO active rows ===")
    rows = read_main_active_uniqlo_rows(sh)
    print(f"  count: {len(rows)}")
    for r in rows[:5]:
        print(f"  row{r['row_index']}: listing={r['listing_id']} title={r['title'][:30]} url={r['url'][:60]}")

    print("\n=== SKU sheet existing rows (sample) ===")
    sku_rows = read_sku_rows(sh)
    print(f"  count: {len(sku_rows)}")
    for r in sku_rows[:3]:
        print(f"  {r}")
