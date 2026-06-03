"""snapshot_reader.py - HQ eBay all-active CSV snapshot から 旧価格 (Current price USD) lookup.

source: user が seller hub から DL する `eBay-all-active-listings-report-YYYY-MM-DD-*.csv`
default path: `C:\\Users\\imax2\\OneDrive\\デスクトップ\\` 配下の最新ファイル

注意: snapshot は時点データ (= 日次)。リアルタイム同期はしない。
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Optional

# default snapshot dir (= 共有データ領域、2026-05-22 自動取得移行)
DEFAULT_SNAPSHOT_DIR = Path(r"C:/dev/iMak_data/snapshots")
# 自動取得ファイル: ebay_active_YYYY-MM-DD_HHMMSS.csv (= Revise が自動 DL)
SNAPSHOT_GLOB = "ebay_active_*.csv"

# fallback: 旧 デスクトップ手動 DL (= 移行期、新 snapshot 未生成時の保険)
FALLBACK_SNAPSHOT_DIR = Path(r"C:/Users/imax2/OneDrive/デスクトップ")
FALLBACK_SNAPSHOT_GLOB = "eBay-all-active-listings-report-*.csv"

# CSV 列名 (= eBay seller hub 出力 schema)
COL_ITEM_NUMBER = "Item number"
COL_TITLE = "Title"
COL_CURRENT_PRICE = "Current price"
COL_CURRENCY = "Currency"
COL_LISTING_SITE = "Listing site"
COL_AVAILABLE_QTY = "Available quantity"


def find_latest_snapshot(snapshot_dir: Path = DEFAULT_SNAPSHOT_DIR) -> Optional[Path]:
    """最新 snapshot CSV path を返す.

    優先順:
      1. snapshot_dir (= 共有データ領域, ebay_active_*.csv)
      2. FALLBACK_SNAPSHOT_DIR (= 旧デスクトップ手動 DL、移行期保険)
    どちらにもなければ None。
    """
    # 1. 共有 dir
    if snapshot_dir.exists():
        files = sorted(snapshot_dir.glob(SNAPSHOT_GLOB),
                       key=lambda p: p.stat().st_mtime, reverse=True)
        if files:
            return files[0]
    # 2. fallback (= 旧デスクトップ)
    if FALLBACK_SNAPSHOT_DIR.exists():
        files = sorted(FALLBACK_SNAPSHOT_DIR.glob(FALLBACK_SNAPSHOT_GLOB),
                       key=lambda p: p.stat().st_mtime, reverse=True)
        if files:
            return files[0]
    return None


def load_snapshot(csv_path: Path) -> dict:
    """snapshot CSV → {ItemID: {"price_usd": float, "title": str, "currency": str, "site": str}}.

    UTF-8 BOM (`\\ufeff`) を吸収。Current price が空欄 / 0 は skip。
    """
    if not csv_path.exists():
        raise FileNotFoundError(f"snapshot CSV が見つかりません: {csv_path}")

    result: dict = {}
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            item_id = (row.get(COL_ITEM_NUMBER) or "").strip()
            if not item_id:
                continue
            price_str = (row.get(COL_CURRENT_PRICE) or "").strip()
            if not price_str:
                continue
            try:
                price = float(price_str.replace(",", ""))
            except ValueError:
                continue
            if price <= 0:
                continue
            # available_qty: 「在庫数」(= 通常 1、0 なら eBay 在庫切れ表示 → revise 意味なし)
            qty_str = (row.get(COL_AVAILABLE_QTY) or "").strip()
            try:
                available_qty = int(float(qty_str)) if qty_str else 0
            except ValueError:
                available_qty = 0
            result[item_id] = {
                "price_usd": price,
                "title": (row.get(COL_TITLE) or "").strip(),
                "currency": (row.get(COL_CURRENCY) or "").strip(),
                "site": (row.get(COL_LISTING_SITE) or "").strip(),
                "available_qty": available_qty,
            }
    return result


def get_old_price(item_id: str, snapshot_map: dict) -> Optional[float]:
    """ItemID → 旧 USD price. snapshot に無ければ None."""
    entry = snapshot_map.get(item_id)
    return entry["price_usd"] if entry else None


def load_variations(csv_path: Path) -> dict:
    """variation 並列 JSON を読込 → {ItemID: [{sku, start_price, quantity, specifics}, ...]}.

    snapshot CSV と同 timestamp の `.variations.json` を探す。なければ空 dict。
    """
    if not csv_path.exists():
        return {}
    # ebay_active_2026-05-24_134007.csv → ebay_active_2026-05-24_134007.variations.json
    var_path = csv_path.parent / (csv_path.stem + ".variations.json")
    if not var_path.exists():
        return {}
    import json as _json
    try:
        return _json.loads(var_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
