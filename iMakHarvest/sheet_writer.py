"""sheet_writer - 収集 URL を Google Sheets に追記 (デデュープ付き).

設計原則:
  - 既存スプシ・列構成を一切壊さない
  - Harvest が書くのは A 列 (URL) のみ. B/C 列は触らない (空欄)
  - デデュープは A 列 URL から item_id を内部抽出して比較
  - 失敗時は raise (caller が retry 判断)
  - 既存行は絶対に上書きしない (新規 append のみ)

スプシ列レイアウト (確定):
  A: 仕入元 URL          ← Harvest が書込 (新規行のみ)
  B: eBay item ID        ← 出品後にユーザー or 別ツールが書込 (Harvest は触らない)
  C: タイトル            ← Harvest が書込
  D: 売切フラグ          ← iMakInventory が書込 (Harvest は触らない)
  E: 商品状態            ← Harvest が書込
  F: 価格                ← Harvest が書込
  G: 画像 URL            ← Harvest が書込 (`|` 区切り)
  H: 商品説明            ← Harvest が書込
  I-R: Harvest 不可侵 (空欄)
  S: 色                  ← Harvest が書込 (Phase 1d)
  T: サイズ              ← Harvest が書込 (Phase 1d)

B 列は eBay item ID (数字のみ) が入るため、Mercari item_id (m\\d+) や
Amazon ASIN とは形式が異なり dedupe key と衝突しない. → デデュープは
A 列 URL のみを参照して判定する.

サービスアカウント認証情報パスは iMakInventory と共通 (CREDS_PATH)。
"""
from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Optional

import gspread
from google.oauth2.service_account import Credentials

CREDS_PATH = r"c:\dev\iMak\double-hold-421922-7c0d38d3f73d.json"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# HIGH/LOW listings シートの既知 ID (iMakInventory.sheet_updater と同じ値)
HIGH_SHEET_ID = "19kj8NqWHIGP1ptQDeGePw077hpdl6dNOO-v2J10HCjk"
LOW_SHEET_ID = "1jF9vggbfUCddjneROMO2GGN-jTAPRbq6Qe2cbgr37B0"
LISTINGS_GID = 851100680  # 商品管理シートタブ (HIGH/LOW 共通)

# 列マッピング (1-based)
COL_URL = 1            # A: 仕入元 URL          - Harvest が書込
COL_EBAY_ITEM_ID = 2   # B: eBay item ID        - 出品後にユーザー / 別ツールが書込 (Harvest は触らない)
COL_TITLE = 3          # C: タイトル            - Harvest が書込
COL_INVENTORY_FLAG = 4 # D: 売り切れフラグ      - iMakInventory が後で書込 (Harvest は触らない)
COL_CONDITION = 5      # E: 商品状態            - Harvest が書込
COL_PRICE = 6          # F: 価格                - Harvest が書込
COL_IMAGES = 7         # G: 画像 URL            - Harvest が書込 (`|` 区切り)
COL_DESCRIPTION = 8    # H: 商品説明            - Harvest が書込
COL_COLOR = 19         # S: 色                  - Harvest が書込 (Phase 1d)
COL_SIZE = 20          # T: サイズ              - Harvest が書込 (Phase 1d)

# Harvest が触らない (空欄 or 既存値保持) すべき列のインデックス set (1-based)
HARVEST_UNTOUCHED_COLS = (COL_EBAY_ITEM_ID, COL_INVENTORY_FLAG)

# 書込み列数 default. A〜T (1-20) を含む 20 列構成.
DEFAULT_COLUMN_COUNT = 20

# デデュープ key 抽出
# - メルカリ通常品: /item/m12345 / /items/m12345 → "m12345" (prefix なし、既存行との互換維持)
# - メルカリ Shops: /shops/product/<slug22> → "shops:<slug>" (prefix で通常品と衝突回避)
# - ワークマン公式: /shop/g/g<13桁mpn>/ → "workman:<mpn>"
# - SNKRDUNK 個別出品: /apparels/<m>/used/<i> → "snkrdunk:<m>/<i>"
# - SNKRDUNK カード本体ページ: /apparels/<m> → "snkrdunk:<m>"
_MERCARI_ID_RE = re.compile(r"/items?/(m\d+)", re.IGNORECASE)
_MERCARI_SHOPS_ID_RE = re.compile(r"/shops/product/([A-Za-z0-9]+)")
_WORKMAN_MPN_RE = re.compile(r"workman\.jp/shop/g/g(\d{13})", re.IGNORECASE)
_SNKRDUNK_USED_RE = re.compile(r"snkrdunk\.com/apparels/(\d+)/used/(\d+)", re.IGNORECASE)
_SNKRDUNK_APPAREL_RE = re.compile(r"snkrdunk\.com/apparels/(\d+)(?:/|$|\?|#)", re.IGNORECASE)


def dedupe_key(url: str) -> str:
    """URL からデデュープ用キーを生成.

    - mercari 通常品 (/item/m12345) → "m12345"
      (既存スプシ行との互換のため prefix を付けない)
    - mercari Shops (/shops/product/<slug>) → "shops:<slug>"
      (通常品の m\\d+ と prefix で衝突回避)
    - workman 公式 (/shop/g/g<mpn>/) → "workman:<mpn>"
    - SNKRDUNK 個別出品 (/apparels/<m>/used/<i>) → "snkrdunk:<m>/<i>"
    - SNKRDUNK カード本体 (/apparels/<m>) → "snkrdunk:<m>"
    - その他: URL 正規化 (query/fragment/末尾スラッシュ除去) + lowercase
    - 空文字なら "" (空 key は append しない側で弾く)
    """
    if not url:
        return ""
    s = url.strip()
    if not s:
        return ""
    # メルカリ通常品 (m\d+)
    m = _MERCARI_ID_RE.search(s)
    if m:
        return m.group(1)
    # メルカリ Shops (slug)
    m = _MERCARI_SHOPS_ID_RE.search(s)
    if m:
        return f"shops:{m.group(1)}"
    # ワークマン公式 (mpn 13 桁)
    m = _WORKMAN_MPN_RE.search(s)
    if m:
        return f"workman:{m.group(1)}"
    # SNKRDUNK 個別出品 (= /apparels/<m>/used/<i>、より specific なので先)
    m = _SNKRDUNK_USED_RE.search(s)
    if m:
        return f"snkrdunk:{m.group(1)}/{m.group(2)}"
    # SNKRDUNK カード本体 (= /apparels/<m>、末尾 or query 区切り)
    m = _SNKRDUNK_APPAREL_RE.search(s)
    if m:
        return f"snkrdunk:{m.group(1)}"
    # 他 supplier 暫定対応: query / fragment / 末尾スラッシュを除去
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

    B 列は eBay item ID (数字のみ) が入る別関心の列なので参照しない.
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
    """item dict から 20 列 (A〜T) の行データを構築.

    - 書込列 (A/C/E/F/G/H/S/T) には値を入れる
    - 触らない列 (B/D, I-R) は "" にして既存値の上書きを避ける
      (※ append_rows は新規行のみ追加するので、新規行の触らない列は空欄になるだけ)
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
    """items を ws に追記 (既出は dedupe_key で除外).

    Args:
        ws:    gspread worksheet
        items: [
                 {
                   "url": str,                 # 必須
                   "title"?: str,
                   "condition"?: str,
                   "price_jpy"?: int | None,
                   "image_urls"?: list[str],
                   "description"?: str,
                   "color"?: str,              # Phase 1d (Vision AI 判定、不明なら空)
                   "size"?: str,               # Phase 1d (Mercari 構造化フィールド)
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

    # 末尾に append (既存行は触らない)
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
    """items を spreadsheet_id の listings シートに書込 (デデュープ付き append).

    入口関数。caller は spreadsheet_id を選んで呼ぶ。
    """
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
    ap.add_argument("--sheet-id", required=True, help="HIGH or LOW spreadsheet ID")
    ap.add_argument("--gid", type=int, default=LISTINGS_GID)
    ap.add_argument("--input", required=True, help="JSON file: [{url, item_id, title?}, ...]")
    args = ap.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        items = json.load(f)
    if not isinstance(items, list):
        print("input must be a JSON list", file=sys.stderr)
        sys.exit(1)

    result = write_to_sheet(items, spreadsheet_id=args.sheet_id, gid=args.gid)
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] result: {result}")
