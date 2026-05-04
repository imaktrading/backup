"""sheet_writer_amazon - Amazon URL を Google Sheets に追記 (ASIN デデュープ).

`sheet_writer.py` の Amazon 版コピー。Mercari の dedupe ロジックは触らず、
Amazon 用に dedupe_key を ASIN ベースに置き換えた独立ファイル。

設計原則 (sheet_writer.py と同じ):
  - 既存スプシ・列構成を一切壊さない
  - 書込列は A/C/E/F/G/H (URL/タイトル/状態/価格/画像/説明)
  - B/D 列は触らない (空欄で append)
  - 失敗時は raise (caller が retry 判断)
  - 既存行は絶対に上書きしない (新規 append のみ)

dedupe ロジックの違い (sheet_writer.py との差分):
  - Amazon URL: /dp/<ASIN>, /gp/product/<ASIN>, /gp/aw/d/<ASIN> から ASIN 抽出
  - dedupe key: "amzn:<ASIN>" (Mercari の "m\\d+" と prefix で衝突しない)
  - 非 Amazon URL (Mercari 等の既存行): URL 正規化フォールバック
    → Mercari 行は Amazon writer から見ると "URL 文字列" として set に入るが、
       新規 Amazon 商品の dedupe key と絶対衝突しない (prefix 違うため)。

Mercari 用の sheet_writer.py には一切影響しない。
"""
from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Optional  # noqa: F401  (CLI 互換のため)

import gspread
from google.oauth2.service_account import Credentials

CREDS_PATH = r"c:\dev\iMak\double-hold-421922-7c0d38d3f73d.json"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# HIGH/LOW listings シートの既知 ID (sheet_writer.py と同じ値)
HIGH_SHEET_ID = "19kj8NqWHIGP1ptQDeGePw077hpdl6dNOO-v2J10HCjk"
LOW_SHEET_ID = "1jF9vggbfUCddjneROMO2GGN-jTAPRbq6Qe2cbgr37B0"
LISTINGS_GID = 851100680  # 商品管理シートタブ (HIGH/LOW 共通)

# 列マッピング (1-based) — sheet_writer.py と同じ
COL_URL = 1            # A: 仕入元 URL          - Harvest が書込
COL_EBAY_ITEM_ID = 2   # B: eBay item ID        - Harvest は触らない
COL_TITLE = 3          # C: タイトル            - Harvest が書込
COL_INVENTORY_FLAG = 4 # D: 売り切れフラグ      - Harvest は触らない
COL_CONDITION = 5      # E: 商品状態
COL_PRICE = 6          # F: 価格
COL_IMAGES = 7         # G: 画像 URL
COL_DESCRIPTION = 8    # H: 商品説明
COL_COLOR = 19         # S: 色                  - Phase 1d (Amazon は基本空欄)
COL_SIZE = 20          # T: サイズ              - Phase 1d (Amazon は基本空欄)

# 書込み列数 default. A〜T (1-20) を含む 20 列構成 (sheet_writer.py と統一).
DEFAULT_COLUMN_COUNT = 20

# dedupe 用 ASIN regex
# /dp/<ASIN>, /gp/product/<ASIN>, /gp/aw/d/<ASIN> をカバー
_AMAZON_ASIN_RE = re.compile(
    r"/(?:dp|gp/product|gp/aw/d)/([A-Z0-9]{10})(?:[/?]|$)",
    re.IGNORECASE,
)


def dedupe_key(url: str) -> str:
    """Amazon URL からデデュープ用キーを生成.

    - Amazon ASIN が抽出できれば "amzn:<ASIN>" を返す (URL 形式違いを吸収)
      例: /dp/B08N5WRWNW と /gp/product/B08N5WRWNW は同一 key
    - 抽出できなければ URL の query/fragment を除いた正規化形を返す
      (Mercari など既存行の dedupe set には URL 文字列が入るが、
       Amazon の "amzn:..." prefix とは絶対に衝突しない)
    - 空文字なら "" を返す
    """
    if not url:
        return ""
    s = url.strip()
    if not s:
        return ""
    m = _AMAZON_ASIN_RE.search(s)
    if m:
        return f"amzn:{m.group(1).upper()}"
    return s.split("?")[0].split("#")[0].rstrip("/").lower()


def open_sheet_by_id(spreadsheet_id: str):
    """サービスアカウント認証 → spreadsheet オブジェクト返却."""
    if not os.path.exists(CREDS_PATH):
        raise FileNotFoundError(f"サービスアカウント JSON が見つかりません: {CREDS_PATH}")
    creds = Credentials.from_service_account_file(CREDS_PATH, scopes=SCOPES)
    gc = gspread.authorize(creds)
    return gc.open_by_key(spreadsheet_id)


def get_listings_worksheet(sh, gid: int = LISTINGS_GID):
    """商品管理シート (gid 一致) を取得. 無ければ最初のシートにフォールバック."""
    for ws in sh.worksheets():
        if ws.id == gid:
            return ws
    return sh.get_worksheet(0)


def read_existing_dedupe_keys(ws) -> set[str]:
    """既存行から デデュープ key の set を取得 (A 列 URL のみ参照).

    Mercari 行は ASIN regex にマッチしないので URL 正規化フォールバック key
    で set に入る (Amazon 用 dedupe では参照されない)。
    """
    all_values = ws.get_all_values()
    if len(all_values) < 2:
        return set()
    keys: set[str] = set()
    for row in all_values[1:]:
        if len(row) >= COL_URL:
            url = (row[COL_URL - 1] or "").strip()
            k = dedupe_key(url)
            if k:
                keys.add(k)
    return keys


def _build_row(item: dict) -> list:
    """item dict から 20 列 (A〜T) の行データを構築. B/D/I-R 列は空欄.

    Amazon items は通常 color/size を持たないため S/T も空欄になる。
    Mercari と同じ列構成を維持することで、HQ 側 listing スクリプトが
    supplier 別分岐なしに同じスプシを読める。
    """
    title = str(item.get("title") or "")
    condition = str(item.get("condition") or "")
    price = item.get("price_jpy")
    price_str = "" if price is None else str(int(price))
    images = item.get("image_urls") or []
    image_str = "|".join(str(u) for u in images if u)
    description = str(item.get("description") or "")
    color = str(item.get("color") or "")
    size = str(item.get("size") or "")

    row = [""] * DEFAULT_COLUMN_COUNT  # A〜T (20 列)
    row[COL_URL - 1] = (item.get("url") or "").strip()
    # COL_EBAY_ITEM_ID (B) は空欄
    row[COL_TITLE - 1] = title
    # COL_INVENTORY_FLAG (D) は空欄
    row[COL_CONDITION - 1] = condition
    row[COL_PRICE - 1] = price_str
    row[COL_IMAGES - 1] = image_str
    row[COL_DESCRIPTION - 1] = description
    # I-R (9-18) は空欄
    row[COL_COLOR - 1] = color
    row[COL_SIZE - 1] = size
    return row


def append_new_urls(
    ws,
    items: list[dict],
    column_count: int = DEFAULT_COLUMN_COUNT,
) -> dict:
    """items を ws に追記 (既出 ASIN は除外).

    Args:
        ws:    gspread worksheet
        items: [
                 {
                   "url": str,                 # 必須 (Amazon /dp/<ASIN> 形式)
                   "title"?: str,
                   "condition"?: str,          # default: "" (caller が "New" 等を指定)
                   "price_jpy"?: int | None,
                   "image_urls"?: list[str],
                   "description"?: str,
                   "color"?: str,              # 通常は空 (Amazon は色構造化フィールド無し)
                   "size"?: str,               # 通常は空 (Amazon は size variation 別ロジック)
                 },
                 ...
               ]
        column_count: 書く列数 (default 20 = A〜T、B/D/I-R は空欄)

    Returns: {"appended": N, "skipped_existing": M, "input": K}
    """
    if not items:
        return {"appended": 0, "skipped_existing": 0, "input": 0}

    existing = read_existing_dedupe_keys(ws)

    new_rows = []
    skipped = 0
    seen_in_batch: set[str] = set()
    for it in items:
        url = (it.get("url") or "").strip()
        if not url:
            skipped += 1
            continue
        key = dedupe_key(url)
        if not key:
            skipped += 1
            continue
        if key in existing or key in seen_in_batch:
            skipped += 1
            continue
        seen_in_batch.add(key)

        row = _build_row(it)
        if len(row) < column_count:
            row += [""] * (column_count - len(row))
        new_rows.append(row[:column_count])

    if not new_rows:
        return {"appended": 0, "skipped_existing": skipped, "input": len(items)}

    ws.append_rows(new_rows, value_input_option="USER_ENTERED")

    return {
        "appended": len(new_rows),
        "skipped_existing": skipped,
        "input": len(items),
    }


def write_to_sheet(
    items: list[dict],
    spreadsheet_id: str,
    gid: int = LISTINGS_GID,
) -> dict:
    """items を spreadsheet_id の listings シートに書込 (ASIN デデュープ付き append)."""
    sh = open_sheet_by_id(spreadsheet_id)
    ws = get_listings_worksheet(sh, gid=gid)
    return append_new_urls(ws, items)


# ============================================================================
# CLI (動作確認用)
# ============================================================================
if __name__ == "__main__":
    import argparse
    import json
    import sys

    ap = argparse.ArgumentParser()
    ap.add_argument("--sheet-id", required=True)
    ap.add_argument("--gid", type=int, default=LISTINGS_GID)
    ap.add_argument("--input", required=True, help="JSON file: [{url, asin, title?, ...}, ...]")
    args = ap.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        items = json.load(f)
    if not isinstance(items, list):
        print("input must be a JSON list", file=sys.stderr)
        sys.exit(1)

    result = write_to_sheet(items, spreadsheet_id=args.sheet_id, gid=args.gid)
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] result: {result}")
