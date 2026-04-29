"""monitor_listings - HIGH/LOW 商品管理シート専用の在庫監視 (Phase 2).

対象スプシ (Takaaki さん確定 2026-04-29):
  - HIGH: 19kj8NqWHIGP1ptQDeGePw077hpdl6dNOO-v2J10HCjk (約 421 商品)
  - LOW : 1jF9vggbfUCddjneROMO2GGN-jTAPRbq6Qe2cbgr37B0 (約 650 商品)
  - 共通 gid: 851100680 (商品管理シート タブ)

スプシ構造:
  A: URL (Mercari/Amazon)
  B: itemID (eBay)
  C: タイトル
  D: 売り切れ ← 本ツールが "○" を書き込む
  ...
  O: 売り切れチェック時間 ← 本ツールが timestamp を書き込む

注: 在庫管理スプシ (101KL6...) は別運用 (バリエ/バンドル特殊管理用)。
本ツールが対象とするのは HIGH/LOW (通常出品) のみ。

実行:
  python monitor_listings.py --sheet high --dry-run --limit 50    # HIGH 最初 50 行 dry-run
  python monitor_listings.py --sheet high                          # HIGH 全件 LIVE
  python monitor_listings.py --sheet both                          # HIGH + LOW 全件
  python monitor_listings.py --sheet high --start 100 --end 150    # 特定行範囲

在庫判定:
  - mercari_scraper / amazon_scraper の `in_stock` フィールドを判定基準とする
  - 取得失敗 (None) → fail-closed: 「自動 ○ 化しない」(=既存 D 列値を維持)
  - 仕入元在庫切れ → D="○" を書く
  - 仕入元在庫あり → D="" にリセット (人手 "○" を上書きする可能性に注意)

Phase 3 連携: 本ツールが書いた "○" を読み取って Revise CSV を生成する。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional

# 同階層モジュール import
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from sheet_updater import (  # noqa: E402
    HIGH_SHEET_ID,
    LOW_SHEET_ID,
    LISTINGS_GID,
    open_sheet_by_id,
    get_listings_worksheet,
    read_listings_rows,
    update_listings_sold_marks,
    detect_supplier,
)
from scrapers.mercari_scraper import fetch_product_inventory as fetch_mercari  # noqa: E402
from scrapers.mercari_scraper import create_driver as create_mercari_driver  # noqa: E402
from scrapers.amazon_scraper import fetch_product_inventory as fetch_amazon  # noqa: E402
from scrapers.amazon_scraper import create_amazon_driver  # noqa: E402
from scrapers.fril_scraper import fetch_product_inventory as fetch_fril  # noqa: E402

LOG_DIR = SCRIPT_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
DECISION_LOG_DIR = SCRIPT_DIR / "decision_log"
DECISION_LOG_DIR.mkdir(parents=True, exist_ok=True)

# Mercari/Amazon 1 リクエストごとの sleep 秒 (anti-bot 対策)
DEFAULT_SLEEP_SEC = 2
# 連続失敗で Selenium fallback を諦める閾値
MAX_CONSEC_FAILURES = 8


def _log_path() -> Path:
    return LOG_DIR / f"listings_{datetime.now().strftime('%Y-%m-%d')}.log"


def log(msg: str):
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line)
    with open(_log_path(), "a", encoding="utf-8") as f:
        f.write(line + "\n")


def _domain_of(url: str) -> str:
    try:
        from urllib.parse import urlparse
        return urlparse(url).netloc.lower()
    except Exception:
        return ""


# ============================================================================
# 1 行 (1 listing) の在庫チェック
# ============================================================================
def check_one_row(row: dict, sleep_sec: float = DEFAULT_SLEEP_SEC,
                  mercari_driver=None, amazon_driver=None) -> dict:
    """1 listing 行の在庫状況を取得し判定結果を返す.

    Args:
        row:            sheet row dict (read_listings_rows の出力)
        sleep_sec:      1 リクエストごとの sleep 秒 (pacing)
        mercari_driver: Selenium driver の再利用 (None なら都度生成)

    Returns: {row_index, url, item_id, supplier, is_sold, raw_status, current_sold, delta, error}
    """
    url = row["url"]
    domain = _domain_of(url)
    supplier = detect_supplier(domain)

    result = {
        "row_index":    row["row_index"],
        "url":          url,
        "item_id":      row.get("item_id", ""),
        "title":        row.get("title", ""),
        "supplier":     supplier,
        "is_sold":      None,
        "raw_status":   "",
        "current_sold": row.get("current_sold", ""),
        "delta":        "uncertain",
        "error":        None,
    }

    if supplier == "mercari":
        try:
            info = fetch_mercari(url, driver=mercari_driver, use_selenium_fallback=False)
        except Exception as e:
            result["error"] = f"{type(e).__name__}: {e}"
            return result
    elif supplier == "amazon":
        try:
            # Selenium fallback 有効: unqualifiedBuyBox 検出時に login profile で
            # personalized buy box (Featured Offer) を再評価する。
            # amazon_driver が None なら fallback path で都度 driver 起動 (遅い)。
            info = fetch_amazon(url, driver=amazon_driver, use_selenium_fallback=True)
        except Exception as e:
            result["error"] = f"{type(e).__name__}: {e}"
            return result
    elif supplier == "fril":
        try:
            info = fetch_fril(url)
        except Exception as e:
            result["error"] = f"{type(e).__name__}: {e}"
            return result
    else:
        result["error"] = f"unsupported supplier: {supplier} ({domain})"
        return result

    # pacing
    time.sleep(sleep_sec)

    if info is None:
        result["error"] = "scraper returned None (fail-closed)"
        return result

    skus = info.get("skus") or []
    if not skus:
        result["error"] = "no skus returned"
        return result

    in_stock = bool(skus[0].get("in_stock", False))
    result["is_sold"] = not in_stock
    result["raw_status"] = info.get("status") or ("in_stock" if in_stock else "out_of_stock")

    # delta 判定
    cur_marked_sold = result["current_sold"] in ("○", "〇")
    if result["is_sold"] and not cur_marked_sold:
        result["delta"] = "newly_sold"
    elif (not result["is_sold"]) and cur_marked_sold:
        result["delta"] = "newly_in_stock"
    else:
        result["delta"] = "unchanged"

    return result


# ============================================================================
# decision_log
# ============================================================================
def append_decision_log(sheet_label: str, results: list, dry_run: bool):
    """decision_log/listings_<ts>.jsonl に追記."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = DECISION_LOG_DIR / f"listings_{sheet_label}_{ts}.jsonl"
    with open(path, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps({
                "ts":           datetime.now().isoformat(timespec="seconds"),
                "sheet":        sheet_label,
                "dry_run":      dry_run,
                **r,
            }, ensure_ascii=False) + "\n")
    log(f"  decision_log: {path}")


# ============================================================================
# pending_revise queue (Phase 3 連携)
# ============================================================================
# 「Phase 2 で今回新規に〇を付与した行のみ」を Phase 3 (Revise CSV) に流す。
# スプシに既存していた手動 〇 や、過去の Inventory 処理で付与された 〇 は
# このキューには入らない → Phase 3/4 で誤って取り下げ対象にしない。
PENDING_REVISE_FILE = DECISION_LOG_DIR / "pending_revise.jsonl"


def append_pending_revise(sheet_label: str, result: dict, dry_run: bool) -> None:
    """delta="newly_sold" の行を pending queue に append.
    dry_run でも記録する (queue 状態の追跡用、ただし Phase 3 側で dry_run flag を尊重)。
    """
    DECISION_LOG_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts":           datetime.now().isoformat(timespec="seconds"),
        "sheet":        sheet_label,
        "row_index":    result["row_index"],
        "url":          result["url"],
        "item_id":      result["item_id"],
        "title":        result.get("title", ""),
        "supplier":     result["supplier"],
        "raw_status":   result["raw_status"],
        "dry_run":      dry_run,
    }
    with open(PENDING_REVISE_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ============================================================================
# 1 spreadsheet (HIGH or LOW) を処理
# ============================================================================
def process_sheet(
    sheet_id: str,
    sheet_label: str,
    start_row: int = 2,
    end_row: Optional[int] = None,
    limit: Optional[int] = None,
    dry_run: bool = False,
    sleep_sec: float = DEFAULT_SLEEP_SEC,
):
    log("=" * 60)
    log(f"商品管理シート [{sheet_label}] 開始 (sheet_id={sheet_id[:20]}..., dry_run={dry_run})")
    log("=" * 60)

    sh = open_sheet_by_id(sheet_id)
    log(f"  open: {sh.title}")
    ws = get_listings_worksheet(sh, gid=LISTINGS_GID)
    log(f"  worksheet: {ws.title} (id={ws.id}, total_rows={ws.row_count})")

    rows = read_listings_rows(ws, start_row=start_row, end_row=end_row, only_with_url=True)
    log(f"  active rows (URL あり): {len(rows)}")

    if limit is not None:
        rows = rows[:limit]
        log(f"  --limit {limit} で絞込: {len(rows)} 件")

    if not rows:
        log("  対象 0 件、終了")
        return {"processed": 0, "newly_sold": 0, "newly_in_stock": 0, "errors": 0}

    # supplier 内訳
    by_sup = {}
    for r in rows:
        sup = detect_supplier(_domain_of(r["url"]))
        by_sup[sup] = by_sup.get(sup, 0) + 1
    log(f"  supplier 内訳: {by_sup}")

    # Mercari URL がある場合は driver を 1 つ生成して再利用 (起動コスト削減)
    mercari_driver = None
    needs_mercari = by_sup.get("mercari", 0) > 0
    if needs_mercari:
        log("  Mercari driver 起動中...")
        try:
            mercari_driver = create_mercari_driver(headless=True)
            log("  ✅ Mercari driver 起動完了 (再利用 mode)")
        except Exception as e:
            log(f"  ⚠️ Mercari driver 起動失敗: {type(e).__name__}: {e}")
            log("     → 各 row で都度 driver 生成に fallback (遅い)")
            mercari_driver = None

    # Amazon URL がある場合は login 済 profile で driver を 1 つ生成 (Selenium fallback 用)
    amazon_driver = None
    needs_amazon = by_sup.get("amazon", 0) > 0
    if needs_amazon:
        log("  Amazon driver 起動中 (login profile)...")
        try:
            amazon_driver = create_amazon_driver(headless=True, use_login_profile=True)
            log("  ✅ Amazon driver 起動完了 (login profile 再利用)")
        except Exception as e:
            log(f"  ⚠️ Amazon driver 起動失敗: {type(e).__name__}: {e}")
            log("     → unqualifiedBuyBox 検出時の Selenium 再判定が無効")
            amazon_driver = None

    results = []
    consec_failures = 0
    for i, row in enumerate(rows, start=1):
        prefix = f"  [{i}/{len(rows)}] row{row['row_index']:>4} "
        try:
            res = check_one_row(row, sleep_sec=sleep_sec,
                                mercari_driver=mercari_driver,
                                amazon_driver=amazon_driver)
        except Exception as e:
            res = {
                "row_index": row["row_index"],
                "url": row["url"],
                "item_id": row.get("item_id", ""),
                "supplier": detect_supplier(_domain_of(row["url"])),
                "is_sold": None,
                "raw_status": "",
                "current_sold": row.get("current_sold", ""),
                "delta": "uncertain",
                "error": f"{type(e).__name__}: {e}",
            }

        # ログ表示
        sup = res["supplier"][:7].ljust(7)
        if res["error"]:
            # 未対応 supplier は skip 扱い (連続失敗カウントに含めない)
            if (res["error"] or "").startswith("unsupported supplier"):
                log(f"{prefix}{sup} - skip ({res['error'][:60]})")
            else:
                consec_failures += 1
                log(f"{prefix}{sup} ⚠️ {res['error'][:60]}")
        else:
            consec_failures = 0
            mark = "○" if res["is_sold"] else "·"
            delta_emoji = {
                "newly_sold":      "🔻",
                "newly_in_stock":  "🔺",
                "unchanged":       " ",
                "uncertain":       "?",
            }.get(res["delta"], "?")
            log(f"{prefix}{sup} {mark} [{res['raw_status'][:14]}] {delta_emoji} {res['delta']}: {row['title'][:30]}")

            # Q2: 「今回新規に〇を付与した行」のみ pending queue に積む
            # → Phase 3 (Revise CSV) は queue から取る = 既存〇は対象外
            if res["delta"] == "newly_sold" and res.get("item_id"):
                append_pending_revise(sheet_label, res, dry_run=dry_run)

        results.append(res)

        # 連続失敗で abort (anti-bot ブロック等)
        if consec_failures >= MAX_CONSEC_FAILURES:
            log(f"  ❌ 連続失敗 {MAX_CONSEC_FAILURES} 件 → abort (anti-bot block 疑い)")
            break

    # driver 後始末
    if mercari_driver is not None:
        try:
            mercari_driver.quit()
        except Exception:
            pass
    if amazon_driver is not None:
        try:
            amazon_driver.quit()
        except Exception:
            pass

    # 集計
    newly_sold = sum(1 for r in results if r["delta"] == "newly_sold")
    newly_in_stock = sum(1 for r in results if r["delta"] == "newly_in_stock")
    errors = sum(1 for r in results if r["error"])
    log("")
    log(f"  === 集計 [{sheet_label}] ===")
    log(f"    処理: {len(results)} / 対象 {len(rows)}")
    log(f"    新規売切: {newly_sold} / 新規復活: {newly_in_stock} / 変化なし: {len(results) - newly_sold - newly_in_stock - errors} / エラー: {errors}")

    # 書込
    updates = []
    for r in results:
        if r["error"] or r["is_sold"] is None:
            continue  # fail-closed: 取得不能なら書込しない
        # 既存 D="○" を上書きしない: 「人手 ○」を尊重する場合の保護
        # 但し、Phase 2 時点では「ツール書込のみ」と仮定し、復活時も "" に戻す
        updates.append({
            "row_index":  r["row_index"],
            "is_sold":    r["is_sold"],
            "checked_at": datetime.now().strftime("%Y/%m/%d %H:%M:%S"),
        })

    if dry_run:
        log("  [DRY RUN] スプシ書込 skip")
        for r in [x for x in results if x["delta"] in ("newly_sold", "newly_in_stock")][:10]:
            log(f"    変化検知サンプル: row{r['row_index']} {r['delta']} {r['url'][:50]}")
    elif updates:
        log(f"  スプシ書込中... ({len(updates)} 件)")
        try:
            res = update_listings_sold_marks(ws, updates)
            log(f"  ✅ updated={res['updated']}")
        except Exception as e:
            log(f"  ❌ スプシ書込失敗: {type(e).__name__}: {e}")
            log(traceback.format_exc())
    else:
        log("  書込対象なし")

    # decision_log は dry_run でも記録
    append_decision_log(sheet_label, results, dry_run)

    log(f"  完了 [{sheet_label}]")
    return {
        "processed":      len(results),
        "newly_sold":     newly_sold,
        "newly_in_stock": newly_in_stock,
        "errors":         errors,
    }


# ============================================================================
# main
# ============================================================================
def main():
    parser = argparse.ArgumentParser(description="HIGH/LOW 商品管理シートの在庫監視 (Phase 2)")
    parser.add_argument("--sheet", choices=["high", "low", "both"], default="high",
                        help="対象 spreadsheet (default: high)")
    parser.add_argument("--start", type=int, default=2, help="開始行 (1-based, default: 2)")
    parser.add_argument("--end", type=int, default=None, help="終了行 (inclusive, None なら全件)")
    parser.add_argument("--limit", type=int, default=None, help="最大処理件数 (start からの相対)")
    parser.add_argument("--dry-run", action="store_true", help="スプシ書込なし、判定のみ")
    parser.add_argument("--sleep", type=float, default=DEFAULT_SLEEP_SEC,
                        help=f"1リクエストごとの sleep 秒 (default: {DEFAULT_SLEEP_SEC})")
    # TEST スプシ向けの sheet ID 上書き (env var fallback)
    parser.add_argument("--high-sheet-id", default=os.environ.get("INVENTORY_HIGH_SHEET_ID"),
                        help="HIGH 用 spreadsheet ID 上書き (env: INVENTORY_HIGH_SHEET_ID)")
    parser.add_argument("--low-sheet-id", default=os.environ.get("INVENTORY_LOW_SHEET_ID"),
                        help="LOW 用 spreadsheet ID 上書き (env: INVENTORY_LOW_SHEET_ID)")
    # 単一スプシ mode (Phase 6a): HIGH/LOW なしで任意 1 件指定
    parser.add_argument("--sheet-id", default=None,
                        help="単一スプシ mode: 指定 ID のみ処理 "
                             "(--high-sheet-id/--low-sheet-id と排他、--sheet 引数は無視)")
    parser.add_argument("--sheet-label", default="SHEET",
                        help="--sheet-id 使用時のラベル (decision_log ファイル名用、default: SHEET)")
    args = parser.parse_args()

    # 単一スプシ mode (Phase 6a)
    if args.sheet_id:
        if args.high_sheet_id or args.low_sheet_id:
            log("❌ --sheet-id と --high-sheet-id/--low-sheet-id は併用不可")
            sys.exit(2)
        log(f"  単一スプシ mode: label={args.sheet_label} id={args.sheet_id[:25]}...")
        targets = [(args.sheet_label, args.sheet_id)]
    else:
        # 既存 HIGH/LOW モード (互換維持)
        high_id = args.high_sheet_id or HIGH_SHEET_ID
        low_id = args.low_sheet_id or LOW_SHEET_ID
        if args.high_sheet_id or args.low_sheet_id:
            log(f"  ⚠️ TEST モード: HIGH={high_id[:25]}... LOW={low_id[:25]}...")
        targets = []
        if args.sheet in ("high", "both"):
            targets.append(("HIGH", high_id))
        if args.sheet in ("low", "both"):
            targets.append(("LOW", low_id))

    grand = {"processed": 0, "newly_sold": 0, "newly_in_stock": 0, "errors": 0}
    for label, sid in targets:
        try:
            stats = process_sheet(
                sheet_id=sid,
                sheet_label=label,
                start_row=args.start,
                end_row=args.end,
                limit=args.limit,
                dry_run=args.dry_run,
                sleep_sec=args.sleep,
            )
            for k, v in stats.items():
                grand[k] = grand[k] + v
        except Exception as e:
            log(f"❌ [{label}] 例外: {type(e).__name__}: {e}")
            log(traceback.format_exc())

    log("=" * 60)
    log(f"全体集計: {grand}")
    log("=" * 60)


if __name__ == "__main__":
    main()
