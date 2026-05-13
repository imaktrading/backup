"""monitor - 仕入元在庫監視オーケストレーション (iMakInventory main entry).

graduation 元: iMakeBayAPI/inventory_monitor/main.py (UNIQLO/montbell only)
本ファイルは Mercari + Amazon を含む全仕入元に拡張した monitor 統合版。

設計原則:
  - 各 supplier scraper は scrapers/<supplier>_scraper.py に独立
  - 失敗時は eBay 自動取り下げを発動しない (Precision 100% 大前提)
  - dry-run mode で安全検証可

実行フロー:
  1. メインシート (101KL6...) から FLG ≠ 1 の listing 行を抽出
  2. supplier ごとに scraper 呼出 → 在庫・価格を取得
  3. SKU シート既存行とマッチング → 対処要判定
  4. SKU シートに update / append (batch)
  5. 要対処件数の前回比較 → 増えたらアラート

実行:
  python monitor.py                          # 全仕入元
  python monitor.py --supplier mercari       # Mercari のみ
  python monitor.py --listing 357401200653   # 特定 listing のみ
  python monitor.py --dry-run                # スプシ書込なし、結果のみ console
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional

# 同階層モジュール import
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from scrapers.uniqlo_scraper import fetch_product_inventory as fetch_uniqlo  # noqa: E402
from scrapers.montbell_scraper import fetch_product_inventory as fetch_montbell  # noqa: E402
from scrapers.mercari_scraper import fetch_product_inventory as fetch_mercari  # noqa: E402
from scrapers.amazon_scraper import fetch_product_inventory as fetch_amazon  # noqa: E402
from ebay_sku_fetcher import get_skus_for_listing  # noqa: E402
from sheet_updater import (  # noqa: E402
    open_sheet,
    read_main_active_rows,
    read_sku_rows,
    update_sku_rows,
    determine_needs_action,
)

LOG_DIR = SCRIPT_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
NEEDS_ACTION_STATE = SCRIPT_DIR / "logs" / "_last_needs_action_count.json"


# ============================================================================
# ロガー (シンプル file + stdout)
# ============================================================================
def _log_path() -> Path:
    return LOG_DIR / f"{datetime.now().strftime('%Y-%m-%d')}.log"


def log(msg: str):
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line)
    with open(_log_path(), "a", encoding="utf-8") as f:
        f.write(line + "\n")


# ============================================================================
# montbell カラー推測: listing title から color code 抽出
# ============================================================================
MONTBELL_COLOR_MAP = {
    "RED": "RD", "BLUE": "BL", "ORANGE": "OG", "BROWN": "BR",
    "BLACK": "BK", "NAVY": "NV", "YELLOW": "YL", "GREEN": "DGN",
    "TURQUOISE": "TQ", "WHITE": "WH",
    "RD": "RD", "BL": "BL", "OG": "OG", "BR": "BR", "BK": "BK",
    "NV": "NV", "YL": "YL", "DGN": "DGN", "TQ": "TQ", "WH": "WH",
}


def guess_montbell_color(title: str) -> Optional[str]:
    t = (title or "").upper()
    for keyword, code in MONTBELL_COLOR_MAP.items():
        if re.search(rf"\b{re.escape(keyword)}\b", t):
            return code
    return None


# ============================================================================
# 仕入元 dispatch
# ============================================================================
SUPPLIERS_SUPPORTED = ("uniqlo", "montbell", "mercari", "amazon")


def fetch_supplier_inventory(supplier: str, url: str, title: str) -> Optional[dict]:
    """supplier に応じて適切な scraper を呼ぶ."""
    if supplier == "uniqlo":
        return fetch_uniqlo(url)
    elif supplier == "montbell":
        color_hint = guess_montbell_color(title)
        return fetch_montbell(url, target_color_code=color_hint)
    elif supplier == "mercari":
        return fetch_mercari(url)
    elif supplier == "amazon":
        return fetch_amazon(url)
    else:
        raise ValueError(f"未対応 supplier: {supplier}")


# ============================================================================
# マッチング: 仕入元 scrape 結果 × SKU シート既存行
# ============================================================================
def _normalize_size(s: str) -> str:
    return (s or "").strip().upper().replace(" ", "")


def _normalize_color(c: str) -> str:
    return (c or "").strip().upper().replace(" ", "")


def match_supplier_skus_with_sheet(
    supplier_skus: list,
    sheet_skus: list,
    listing_default_color: str = "",
) -> list:
    """仕入元 scraper の SKU と SKU シート既存行を (size, color) compound key で match."""
    matched = []
    for sup in supplier_skus:
        u_size = _normalize_size(sup.get("size", ""))
        u_color = _normalize_color(sup.get("color_code") or listing_default_color)

        existing = None
        for sh_sku in sheet_skus:
            if (_normalize_size(sh_sku.get("size", "")) == u_size
                    and _normalize_color(sh_sku.get("color", "")) == u_color):
                existing = sh_sku
                break
        if existing is None:
            for sh_sku in sheet_skus:
                if _normalize_size(sh_sku.get("size", "")) == u_size:
                    existing = sh_sku
                    break

        matched.append({
            "row_index":         existing["row_index"] if existing else None,
            "sku_id":            existing["sku_id"] if existing else "",
            "size":              sup.get("size", ""),
            "color":             sup.get("color_code") or listing_default_color,
            "supplier_in_stock": sup.get("in_stock", False),
            "supplier_quantity": sup.get("quantity", 0),
            "supplier_price":    sup.get("price_jpy"),
            "ebay_qty":          existing["ebay_qty"] if existing else 0,
            "uniqlo_l2id":       sup.get("l2Id", ""),
            "uniqlo_communication_code": sup.get("communication_code", ""),
        })
    return matched


# ============================================================================
# 1 listing 処理
# ============================================================================
def process_listing(sh, main_row: dict, dry_run: bool = False) -> dict:
    """1 listing 分の処理. Returns: {"updates": [...], "needs_action_count": N}"""
    listing_id = main_row["listing_id"]
    title = main_row["title"]
    url = main_row["url"]
    supplier = main_row.get("supplier", "uniqlo")

    log(f"  ▶ listing {listing_id} [{supplier}] ({title[:30]})")

    try:
        info = fetch_supplier_inventory(supplier, url, title)
    except Exception as e:
        log(f"    [!] {supplier} scrape 失敗: {type(e).__name__}: {e}")
        return {"updates": [], "needs_action_count": 0, "error": str(e)}

    if info is None:
        log(f"    [!] {supplier} scrape: 取得不能 (None 返却)")
        return {"updates": [], "needs_action_count": 0, "error": "scraper returned None"}

    log(f"    {supplier}: {info.get('name', '?')[:40]} / {info.get('color', '')} / {len(info.get('skus', []))} skus")

    # SKU シート読込
    all_sku_rows = read_sku_rows(sh)
    sheet_skus = get_skus_for_listing(listing_id, mode="stub_from_sheet", sheet_rows=all_sku_rows)

    listing_default_color = info.get("color", "") if info.get("color", "") not in ("ALL", "") else ""
    matched = match_supplier_skus_with_sheet(info.get("skus", []), sheet_skus, listing_default_color)

    updates = []
    needs_action_count = 0
    auto_check_at = datetime.now().strftime("%Y/%m/%d %H:%M")
    for m in matched:
        needs_action = determine_needs_action(
            supplier_in_stock=m["supplier_in_stock"],
            ebay_qty=m["ebay_qty"],
        )
        # 偽陽性防止: eBay SKU ID が空欄 = 「人手で eBay SKU を紐付けるまで未確定」
        # シート未登録 (row_index is None) も未確定。
        # ただし Mercari/Amazon の 1 商品 = 1 SKU 仕入元では SKU ID 不要のためスキップしない。
        if supplier in ("uniqlo", "montbell"):
            if m["row_index"] is None or not (m["sku_id"] or "").strip():
                needs_action = False
        if needs_action:
            needs_action_count += 1

        sku_id = m["sku_id"]
        color = m["color"] or listing_default_color

        updates.append({
            "row_index":            m["row_index"],
            "listing_id":           listing_id,
            "title":                title,
            "sku_id":               sku_id,
            "size":                 m["size"],
            "color":                color,
            "supplier_stock_mark":  "◎" if m["supplier_in_stock"] else "✕",
            "supplier_price":       m["supplier_price"],
            "ebay_qty":             m["ebay_qty"],
            "auto_check_at":        auto_check_at,
            "needs_action":         needs_action,
        })

    in_stock_count = sum(1 for m in matched if m["supplier_in_stock"])
    log(f"    在庫: {in_stock_count}/{len(matched)} あり, 要対処: {needs_action_count}")

    return {"updates": updates, "needs_action_count": needs_action_count}


# ============================================================================
# アラート (Phase 1: console 出力のみ)
# ============================================================================
def alert_if_increased(current: int) -> None:
    last = 0
    if NEEDS_ACTION_STATE.exists():
        try:
            last = json.loads(NEEDS_ACTION_STATE.read_text(encoding="utf-8")).get("count", 0)
        except Exception:
            last = 0

    if current > last:
        diff = current - last
        log("=" * 60)
        log(f"[!] 要対処件数 増加: 前回 {last} → 今回 {current} (+{diff})")
        log(f"   SKU シート確認: https://docs.google.com/spreadsheets/d/{(__import__('sheet_updater').SPREADSHEET_ID)}/edit")
        log("=" * 60)
    else:
        log(f"  要対処件数: 前回 {last} → 今回 {current} (増加なし)")

    NEEDS_ACTION_STATE.write_text(
        json.dumps({"count": current, "checked_at": datetime.now().isoformat()}, ensure_ascii=False),
        encoding="utf-8",
    )


# ============================================================================
# main
# ============================================================================
def main():
    parser = argparse.ArgumentParser(description="仕入元在庫監視 (iMakInventory monitor)")
    parser.add_argument("--listing", help="特定 listing ID のみ処理")
    parser.add_argument("--supplier", choices=("all",) + SUPPLIERS_SUPPORTED, default="all",
                        help="特定仕入元のみ処理 (default: all)")
    parser.add_argument("--dry-run", action="store_true", help="スプシ書込なし")
    args = parser.parse_args()

    log("=" * 60)
    log(f"在庫監視 開始 ({'DRY RUN' if args.dry_run else 'LIVE'}) supplier={args.supplier}")
    log("=" * 60)

    try:
        sh = open_sheet()
        log(f"スプシ open: {sh.title}")
    except Exception as e:
        log(f"[NG] スプシ認証失敗: {type(e).__name__}: {e}")
        log(traceback.format_exc())
        sys.exit(1)

    main_rows = read_main_active_rows(sh, supplier_filter=args.supplier)
    by_sup = {}
    for r in main_rows:
        by_sup[r["supplier"]] = by_sup.get(r["supplier"], 0) + 1
    log(f"メインシート active 行: {len(main_rows)} 件 ({by_sup})")

    if args.listing:
        main_rows = [r for r in main_rows if r["listing_id"] == args.listing]
        log(f"--listing {args.listing} で絞り込み → {len(main_rows)} 件")

    if not main_rows:
        log("対象 0 件、終了")
        return

    all_updates = []
    total_needs_action = 0
    errors = []
    for row in main_rows:
        try:
            result = process_listing(sh, row, dry_run=args.dry_run)
            all_updates.extend(result["updates"])
            total_needs_action += result["needs_action_count"]
            if result.get("error"):
                errors.append((row["listing_id"], result["error"]))
        except Exception as e:
            errors.append((row["listing_id"], f"{type(e).__name__}: {e}"))
            log(f"    [NG] listing {row['listing_id']} 例外: {e}")
            log(traceback.format_exc())

    log("")
    log("=== 集計 ===")
    log(f"  処理 listing: {len(main_rows)}")
    log(f"  生成 update : {len(all_updates)}")
    log(f"  要対処 SKU  : {total_needs_action}")
    log(f"  エラー       : {len(errors)}")
    for lid, msg in errors:
        log(f"    - {lid}: {msg}")

    if args.dry_run:
        log("\n[DRY RUN] スプシ書込スキップ")
        for u in all_updates[:5]:
            log(f"  サンプル update: {u}")
    elif all_updates:
        log(f"\nスプシ書込中... ({len(all_updates)} 件)")
        try:
            r = update_sku_rows(sh, all_updates)
            log(f"  [OK] updated={r['updated']}, appended={r['appended']}")
        except Exception as e:
            log(f"  [NG] スプシ書込失敗: {type(e).__name__}: {e}")
            log(traceback.format_exc())
            sys.exit(1)

    alert_if_increased(total_needs_action)

    log("=" * 60)
    log("完了")


if __name__ == "__main__":
    main()
