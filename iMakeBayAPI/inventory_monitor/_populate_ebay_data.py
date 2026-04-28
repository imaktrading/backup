"""_populate_ebay_data - eBay Browse API で SKU シートの F/K 列を初回シード.

設計:
  - Browse API `get_items_by_item_group` で各 listing の variation 一覧取得
  - Variation の "Sizes" aspect から JP サイズ抽出 ("US XS(JP S)" → "S")
  - SKU シートの listing_id × JP size でマッチ → F/K 列更新

注意:
  - Browse API では seller の内部 SKU (sku_id) は取れないので
    variation の itemId (eBay 内部 ID, "v1|357401200653|626268275490" 形式の末尾) を
    代用として F 列に入れる
  - estimatedAvailableQuantity を K 列に入れる (1=出品中, 0=停止)

実行:
  python _populate_ebay_data.py            # 全 listing 充填
  python _populate_ebay_data.py --listing 357401200653  # 特定のみ
  python _populate_ebay_data.py --dry-run  # スプシ書込なし、結果のみ表示
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

# iMakeBayAPI を sys.path に追加
_IMAK_EBAY_API = SCRIPT_DIR.parent
if str(_IMAK_EBAY_API) not in sys.path:
    sys.path.insert(0, str(_IMAK_EBAY_API))

from sheet_updater import open_sheet, get_sku_worksheet  # noqa: E402


# eBay variation "Sizes" aspect のパース ("US XS(JP S)" → ("XS", "S"))
_SIZE_PATTERN = re.compile(r"US\s+([\w]+)\s*\(JP\s+([\w]+)\)", re.IGNORECASE)


def parse_size_aspect(sizes_value: str) -> tuple:
    """'US XS(JP S)' → ('XS', 'S').  括弧無しなら ('S', 'S') 等."""
    if not sizes_value:
        return ("", "")
    m = _SIZE_PATTERN.search(sizes_value)
    if m:
        return (m.group(1), m.group(2))
    # 括弧なし = JP サイズだけ ("S" 等)
    sz = sizes_value.strip().upper()
    return (sz, sz)


def get_variations(listing_id: str) -> list:
    """Browse API で listing の全 variation 取得.

    Returns: [
        {
            "variation_item_id": "626268275490",
            "us_size": "XS",
            "jp_size": "S",
            "color":   "BK",      # eBay の Color aspect (montbell は code そのまま)
            "in_stock": True,
            "quantity": 1,
        },
        ...
    ]
    """
    from check_csv_core import load_ebay_keys, get_oauth_token  # noqa: E402
    import requests  # noqa: E402

    keys = load_ebay_keys()
    app_id = keys.get("AppID")
    app_secret = keys.get("CertID") or keys.get("AppSecret")
    if not (app_id and app_secret):
        raise RuntimeError("eBay API credentials 未設定 (iMakeBayAPI/ebay keys.txt)")

    token = get_oauth_token(app_id, app_secret)
    url = "https://api.ebay.com/buy/browse/v1/item/get_items_by_item_group"
    headers = {
        "Authorization": f"Bearer {token}",
        "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
    }
    resp = requests.get(url, headers=headers, params={"item_group_id": listing_id}, timeout=20)
    if resp.status_code != 200:
        raise RuntimeError(f"Browse API HTTP {resp.status_code}: {resp.text[:200]}")
    data = resp.json()
    items = data.get("items", [])

    variations = []
    for it in items:
        # itemId 形式: "v1|357401200653|626268275490" → 末尾だけ抽出
        full_id = it.get("itemId", "")
        var_id = full_id.split("|")[-1] if "|" in full_id else full_id

        # Sizes / Color aspect 取り出し
        size_value = ""
        color_value = ""
        for asp in it.get("localizedAspects", []):
            if asp.get("name") == "Sizes":
                size_value = asp.get("value", "")
            elif asp.get("name") == "Color":
                color_value = asp.get("value", "")
        us_sz, jp_sz = parse_size_aspect(size_value)

        # 在庫
        avails = it.get("estimatedAvailabilities", [])
        in_stock = False
        qty = 0
        if avails:
            a0 = avails[0]
            in_stock = a0.get("estimatedAvailabilityStatus") == "IN_STOCK"
            qty = a0.get("estimatedAvailableQuantity", 0) or 0

        variations.append({
            "variation_item_id": var_id,
            "us_size": us_sz,
            "jp_size": jp_sz,
            "color":   color_value,
            "in_stock": in_stock,
            "quantity": qty,
        })
    return variations


def populate(listing_filter: str = None, dry_run: bool = False):
    sh = open_sheet()
    sku_ws = get_sku_worksheet(sh)
    all_values = sku_ws.get_all_values()
    if len(all_values) < 2:
        print("SKU シート空、終了")
        return

    # listing_id → variation list キャッシュ
    listing_ids = sorted(set(row[3] for row in all_values[1:] if len(row) > 3 and row[3]))
    if listing_filter:
        listing_ids = [x for x in listing_ids if x == listing_filter]

    print(f"対象 listing: {len(listing_ids)}")

    listing_variations = {}
    for lid in listing_ids:
        try:
            vars_list = get_variations(lid)
            listing_variations[lid] = vars_list
            in_stock_n = sum(1 for v in vars_list if v["in_stock"])
            print(f"  {lid}: {len(vars_list)} variations, {in_stock_n} in_stock")
        except Exception as e:
            print(f"  ❌ {lid}: {type(e).__name__}: {e}")
            listing_variations[lid] = []

    # シート行を listing_id × (JP size, color) compound key でマッチして F/K 更新
    cell_updates = []
    matched = 0
    unmatched = 0
    for row_idx, row in enumerate(all_values[1:], start=2):
        if len(row) < 8:
            continue
        lid = row[3]
        sheet_size = (row[6] or "").strip().upper()
        sheet_color = (row[7] or "").strip().upper()
        if lid not in listing_variations:
            continue
        vars_list = listing_variations[lid]

        # 1. compound match (size + color)
        match = None
        if sheet_color:
            for v in vars_list:
                if (v["jp_size"].upper() == sheet_size and v["color"].upper() == sheet_color):
                    match = v
                    break
            if match is None:
                for v in vars_list:
                    if (v["us_size"].upper() == sheet_size and v["color"].upper() == sheet_color):
                        match = v
                        break

        # 2. size-only fallback (1 listing = 1 color の UNIQLO 単純カラー)
        if match is None:
            for v in vars_list:
                if v["jp_size"].upper() == sheet_size:
                    match = v
                    break
            if match is None:
                for v in vars_list:
                    if v["us_size"].upper() == sheet_size:
                        match = v
                        break

        if match is None:
            unmatched += 1
            continue

        # F 列 (sku_id), K 列 (eBay 現Qty) のみ更新
        cell_updates.append({
            "range": f"F{row_idx}",
            "values": [[match["variation_item_id"]]],
        })
        cell_updates.append({
            "range": f"K{row_idx}",
            "values": [[match["quantity"]]],
        })
        matched += 1

    print(f"\n=== マッチ結果 ===")
    print(f"  マッチ成功: {matched} 行")
    print(f"  マッチ失敗: {unmatched} 行 (eBay 側に該当 variation なし)")

    if dry_run:
        print("\n[DRY RUN] スプシ書込スキップ")
        for u in cell_updates[:6]:
            print(f"  {u['range']} ← {u['values']}")
        return

    if cell_updates:
        print(f"\nスプシ書込中... ({len(cell_updates)} cell)")
        sku_ws.batch_update(cell_updates, value_input_option="USER_ENTERED")
        print("  ✅ 完了")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--listing", help="特定 listing のみ")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    populate(args.listing, args.dry_run)
