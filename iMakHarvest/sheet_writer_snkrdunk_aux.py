"""sheet_writer_snkrdunk_aux - 統合 Hight スプシ AC-AG 列への補仕入 URL 投入専用 writer.

iMakTCG 既存 listing に対し、SNKRDUNK PSA10 補仕入 URL を AC〜AG 列 (col 29〜33) に
最大 5 件 追記する。既存値は touch なし、空き列に左詰めで投入。

既存 commit `75544b1` (ichibankuji 補 URL 実装) で AC-AG 列構造確保済。
本 module は Harvest 側から AC-AG への書込専用、HQ 側 listing スクリプトは読込側。

設計原則:
  - 既存 sheet_writer.py / sheet_writer_*.py は touch なし、独立分離
  - 既存 AC-AG 値は絶対に上書きしない (= URL 完全一致 dedup、空き列にのみ投入)
  - 5 列全部埋まり時は投入 skip + ログ (= overflow 警告)
  - 失敗時は raise (caller が retry 判断)

スプシ列 (1-based):
  A〜H : Harvest 既存書込 (URL / item ID / Title / 売切 / Cond / Price / Image / Desc)
  I〜R : (Harvest 不可侵)
  S    : 色 (Harvest 書込、Phase 1d)
  T    : サイズ (Harvest 書込、Phase 1d)
  ... U〜AB : (Harvest 不可侵)
  AC〜AG : 補仕入 URL 1〜5 (本 module 書込)
"""
from __future__ import annotations

import os
from datetime import datetime

import gspread
from google.oauth2.service_account import Credentials

from sheet_writer import HIGH_SHEET_ID, LISTINGS_GID, LOW_SHEET_ID

CREDS_PATH = r"c:\dev\iMak\double-hold-421922-7c0d38d3f73d.json"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# AC〜AG 列 (1-based)、commit `75544b1` 既存実装の補仕入 URL 1〜5
COL_AUX_URL_1 = 29   # AC: 補仕入 URL 1
COL_AUX_URL_2 = 30   # AD: 補仕入 URL 2
COL_AUX_URL_3 = 31   # AE: 補仕入 URL 3
COL_AUX_URL_4 = 32   # AF: 補仕入 URL 4
COL_AUX_URL_5 = 33   # AG: 補仕入 URL 5
AUX_URL_COLUMNS = (COL_AUX_URL_1, COL_AUX_URL_2, COL_AUX_URL_3, COL_AUX_URL_4, COL_AUX_URL_5)
AUX_URL_LETTERS = ("AC", "AD", "AE", "AF", "AG")


def _col_letter(col_1based: int) -> str:
    """1-based 列番号 → A1 形式の文字 (例: 29 → AC)."""
    s = ""
    n = col_1based
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def open_sheet_by_id(spreadsheet_id: str):
    """サービスアカウント認証 → spreadsheet オブジェクト返却."""
    if not os.path.exists(CREDS_PATH):
        raise FileNotFoundError(f"サービスアカウント JSON が見つかりません: {CREDS_PATH}")
    creds = Credentials.from_service_account_file(CREDS_PATH, scopes=SCOPES)
    gc = gspread.authorize(creds)
    return gc.open_by_key(spreadsheet_id)


def get_listings_worksheet(sh, gid: int = LISTINGS_GID):
    """商品管理シート (gid 一致) を取得."""
    for ws in sh.worksheets():
        if ws.id == gid:
            return ws
    return sh.get_worksheet(0)


def find_empty_aux_columns(row_values: list[str]) -> list[int]:
    """指定行の AC〜AG 列のうち、空欄になっている列番号 (1-based) リストを左詰めで返す.

    Args:
        row_values: ws.row_values() で取得した行 (1-based の列順、リスト)

    Returns: 空欄列の 1-based 列番号 (例: [29, 31] なら AC と AE が空欄)
    """
    empty_cols: list[int] = []
    for col in AUX_URL_COLUMNS:
        # row_values が AC 列 (29) より短い → 全部空欄
        if len(row_values) < col:
            empty_cols.append(col)
            continue
        cell = (row_values[col - 1] or "").strip()
        if not cell:
            empty_cols.append(col)
    return empty_cols


def get_existing_aux_urls(row_values: list[str]) -> set[str]:
    """指定行の AC〜AG 列に既に入っている URL の set を返す (dedup 用)."""
    urls: set[str] = set()
    for col in AUX_URL_COLUMNS:
        if len(row_values) < col:
            continue
        cell = (row_values[col - 1] or "").strip()
        if cell:
            urls.add(cell)
    return urls


def plan_aux_url_inserts(
    row_values: list[str],
    candidate_urls: list[str],
) -> list[tuple[int, str]]:
    """投入計画を立てる (= どの列にどの URL を投入するか).

    Args:
        row_values: 該当行の現状値
        candidate_urls: 候補 URL list (=スニダン PSA10 URL)

    Returns: [(col_1based, url), ...] 最大 5 件、空き列に左詰めで割り当て
        - 既存 AC-AG 内の URL とは dedup
        - candidate_urls 内の重複も dedup (前出優先)
        - 空き列なくなったら投入終了
    """
    existing_urls = get_existing_aux_urls(row_values)
    empty_cols = find_empty_aux_columns(row_values)
    if not empty_cols:
        return []  # 空き列なし、investment skip

    plans: list[tuple[int, str]] = []
    seen_in_batch: set[str] = set()
    for url in candidate_urls:
        url = (url or "").strip()
        if not url:
            continue
        if url in existing_urls or url in seen_in_batch:
            continue
        if not empty_cols:
            break
        col = empty_cols.pop(0)
        plans.append((col, url))
        seen_in_batch.add(url)
    return plans


def apply_aux_url_inserts(
    ws,
    row_index: int,
    plans: list[tuple[int, str]],
) -> int:
    """投入計画を実行 (= 指定セルへ書込).

    Args:
        ws: gspread worksheet
        row_index: 1-based 行番号
        plans: plan_aux_url_inserts の出力

    Returns: 投入セル数
    """
    if not plans:
        return 0
    # batch_update で一括書込み (= 各セル個別 update より高速)
    batch_data = []
    for col, url in plans:
        cell_addr = f"{_col_letter(col)}{row_index}"
        batch_data.append({"range": cell_addr, "values": [[url]]})
    ws.batch_update(batch_data, value_input_option="USER_ENTERED")
    return len(plans)


def insert_aux_urls_for_row(
    ws,
    row_index: int,
    row_values: list[str],
    candidate_urls: list[str],
) -> dict:
    """1 行分の補仕入 URL 投入 (計画 + 実行を一括)。

    Args:
        ws: gspread worksheet
        row_index: 1-based 行番号
        row_values: 該当行の現状値 (= ws.row_values(row_index) の戻り値)
        candidate_urls: 候補 URL list (5 件以上あっても上から 5 件のみ採用)

    Returns:
        {
            "inserted": N (投入セル数),
            "skipped_existing": M (既存値と重複した URL 数),
            "skipped_overflow": K (空き列なくて投入できなかった URL 数),
            "plans": [(col_letter, url), ...],  # 投入詳細 (ログ用)
        }
    """
    existing_urls = get_existing_aux_urls(row_values)
    plans = plan_aux_url_inserts(row_values, candidate_urls)

    # 統計算出
    inserted = 0
    if plans:
        inserted = apply_aux_url_inserts(ws, row_index, plans)

    skipped_existing = 0
    for url in candidate_urls:
        url_s = (url or "").strip()
        if url_s and url_s in existing_urls:
            skipped_existing += 1

    skipped_overflow = max(
        0,
        len(set((u or "").strip() for u in candidate_urls if u) - existing_urls) - len(plans),
    )

    return {
        "inserted": inserted,
        "skipped_existing": skipped_existing,
        "skipped_overflow": skipped_overflow,
        "plans": [(_col_letter(col), url) for col, url in plans],
    }


# ============================================================================
# CLI (動作確認用、本番投入は run_harvest_snkrdunk.py 経由)
# ============================================================================
if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--sheet", choices=["high", "low"], default="high",
        help="対象スプシ (統合 Hight = HIGH)"
    )
    ap.add_argument("--row", type=int, required=True, help="対象行番号 (1-based)")
    ap.add_argument("--urls", required=True, help="補仕入 URL カンマ区切り (最大 5 件)")
    args = ap.parse_args()

    sheet_id = HIGH_SHEET_ID if args.sheet == "high" else LOW_SHEET_ID
    sh = open_sheet_by_id(sheet_id)
    ws = get_listings_worksheet(sh, gid=LISTINGS_GID)
    row_values = ws.row_values(args.row)
    candidate_urls = [u.strip() for u in args.urls.split(",") if u.strip()]
    result = insert_aux_urls_for_row(ws, args.row, row_values, candidate_urls)
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] result: {result}")
