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
    _domain_of,
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
# Mercari driver の連続 None で driver を再起動する閾値 (anti-bot 復帰試行)
# Phase 9: 旧 MAX_CONSEC_FAILURES (=8) で全 supplier 早期 abort していたが、
# 漏れ NG 原則のため abort 廃止し、driver 再起動 + ループ続行で全件処理する
MERCARI_RESTART_THRESHOLD = 5


def _log_path() -> Path:
    return LOG_DIR / f"listings_{datetime.now().strftime('%Y-%m-%d')}.log"


def log(msg: str):
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line)
    with open(_log_path(), "a", encoding="utf-8") as f:
        f.write(line + "\n")


# ============================================================================
# 1 行 (1 listing) の在庫チェック
# ============================================================================
def _check_single_url(url: str, sleep_sec: float = DEFAULT_SLEEP_SEC,
                      mercari_driver=None, amazon_driver=None) -> dict:
    """1 URL に対する scraper 呼出 + 結果 dict 返却 (純粋 helper).

    Returns: {url, supplier, is_sold (True/False/None), raw_status, error, price_jpy}
        - is_sold=False: 在庫あり (= 取下げ対象外)
        - is_sold=True : 売切 (= 取下げ候補)
        - is_sold=None : 不確定 (scraper 失敗等、error 必ず非 None)
    """
    domain = _domain_of(url)
    supplier = detect_supplier(domain)
    out = {"url": url, "supplier": supplier, "is_sold": None,
           "raw_status": "", "error": None, "price_jpy": None}

    if supplier == "mercari":
        try:
            info = fetch_mercari(url, driver=mercari_driver, use_selenium_fallback=False)
        except Exception as e:
            out["error"] = f"{type(e).__name__}: {e}"
            return out
    elif supplier == "amazon":
        try:
            info = fetch_amazon(url, driver=amazon_driver, use_selenium_fallback=True)
        except Exception as e:
            out["error"] = f"{type(e).__name__}: {e}"
            return out
    elif supplier == "fril":
        try:
            info = fetch_fril(url)
        except Exception as e:
            out["error"] = f"{type(e).__name__}: {e}"
            return out
    else:
        out["error"] = f"unsupported supplier: {supplier} ({domain})"
        return out

    time.sleep(sleep_sec)

    if info is None:
        out["error"] = "scraper returned None (fail-closed)"
        return out
    skus = info.get("skus") or []
    if not skus:
        out["error"] = "no skus returned"
        return out

    in_stock = bool(skus[0].get("in_stock", False))
    out["is_sold"] = not in_stock
    out["raw_status"] = info.get("status") or ("in_stock" if in_stock else "out_of_stock")

    raw_price = skus[0].get("price_jpy")
    if isinstance(raw_price, int) and not isinstance(raw_price, bool) and raw_price >= 0:
        out["price_jpy"] = raw_price

    return out


def check_one_row(row: dict, sleep_sec: float = DEFAULT_SLEEP_SEC,
                  mercari_driver=None, amazon_driver=None) -> dict:
    """1 listing 行の在庫状況を取得し判定結果を返す (主 URL のみ、後方互換 API).

    補仕入URL を含む短絡評価が必要な場合は check_one_row_with_fallback を使うこと。
    """
    sub = _check_single_url(row["url"], sleep_sec, mercari_driver, amazon_driver)
    return _build_row_result(row, [sub], hit_index=(0 if sub["is_sold"] is False else -1))


def check_one_row_with_fallback(row: dict, sleep_sec: float = DEFAULT_SLEEP_SEC,
                                 mercari_driver=None, amazon_driver=None) -> dict:
    """主 URL + 補仕入URL 1〜5 で短絡評価.

    判定ルール (出品の正確性原則: Precision 100%):
        - 1 候補でも明確に在庫あり (is_sold=False) → 即 return (in_stock 確定、残り skip)
        - 全候補チェック完了で全部 is_sold=True かつ error 無し → newly_sold 判定
        - error が 1 件でも残ると → uncertain (= 取下げ skip、安全側)

    Returns: 既存 check_one_row と同じ形式 (row_index, url, item_id, supplier,
             is_sold, raw_status, current_sold, delta, error, price_jpy, candidates_checked)
    """
    backup_urls = row.get("backup_urls", []) or []
    candidates = [row["url"]] + backup_urls
    sub_results = []
    for idx, url in enumerate(candidates):
        sub = _check_single_url(url, sleep_sec, mercari_driver, amazon_driver)
        sub_results.append(sub)
        if sub["is_sold"] is False:
            # 短絡: 在庫あり確定、残り skip
            return _build_row_result(row, sub_results, hit_index=idx)
    # 短絡無しで全候補チェック完了
    return _build_row_result(row, sub_results, hit_index=-1)


def _build_row_result(row: dict, sub_results: list, hit_index: int) -> dict:
    """sub_results 群から row 単位の最終結果 dict を組み立てる.

    Args:
        sub_results: _check_single_url の出力 list (1 件以上)
        hit_index:   短絡 hit した sub の index (= 在庫あり)、-1 なら短絡なし
    """
    main_sub = sub_results[0]
    if hit_index >= 0:
        # 在庫あり確定 (短絡 hit)
        hit = sub_results[hit_index]
        is_sold = False
        error = None
        if hit_index == 0:
            raw_status = hit["raw_status"] or "in_stock"
        else:
            raw_status = f"in_stock@backup#{hit_index} ({hit['raw_status'] or 'in_stock'})"
        price_jpy = hit["price_jpy"]   # 在庫ありの URL の価格を採用
    else:
        # 短絡 hit なし: 全候補 is_sold=True (全部売切) or error 含む
        has_error = any(s["error"] for s in sub_results)
        all_sold_clean = all(s["is_sold"] is True for s in sub_results)
        if all_sold_clean and not has_error:
            is_sold = True
            error = None
            n = len(sub_results)
            raw_status = f"all_sold ({n}/{n})" if n > 1 else (main_sub["raw_status"] or "out_of_stock")
            # 全部売切 → 価格は意味ないが、主 URL の最終価格を残す
            price_jpy = main_sub["price_jpy"]
        else:
            # error 含む → 不確定 (Precision 100%、取下げ skip)
            is_sold = None
            err_count = sum(1 for s in sub_results if s["error"])
            n = len(sub_results)
            if n == 1:
                error = main_sub["error"] or "unknown"
            else:
                # 複数候補で 1 つ以上エラー → 主 URL のエラーを優先表示
                first_err = next((s["error"] for s in sub_results if s["error"]), None)
                error = f"uncertain: {err_count}/{n} candidates errored ({first_err})"
            raw_status = ""
            price_jpy = None

    result = {
        "row_index":         row["row_index"],
        "url":               row["url"],
        "item_id":           row.get("item_id", ""),
        "title":             row.get("title", ""),
        "supplier":          main_sub["supplier"],
        "is_sold":           is_sold,
        "raw_status":        raw_status,
        "current_sold":      row.get("current_sold", ""),
        "delta":             "uncertain",
        "error":             error,
        "price_jpy":         price_jpy,
        "candidates_checked": len(sub_results),
    }

    # delta 判定
    cur_marked_sold = result["current_sold"] in ("○", "〇")
    if is_sold is True and not cur_marked_sold:
        result["delta"] = "newly_sold"
    elif is_sold is False and cur_marked_sold:
        result["delta"] = "newly_in_stock"
    elif is_sold in (True, False):
        result["delta"] = "unchanged"
    # is_sold=None (error) は uncertain のまま

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
    progress_callback=None,
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
    mercari_consec_none = 0  # Phase 9: mercari driver 自動再起動用カウンタ
    total_rows = len(rows)
    if progress_callback is not None:
        try:
            progress_callback(phase="monitor", processed=0, total=total_rows, errors=0,
                              sheet_label=sheet_label)
        except Exception:
            pass
    for i, row in enumerate(rows, start=1):
        prefix = f"  [{i}/{total_rows}] row{row['row_index']:>4} "
        try:
            res = check_one_row_with_fallback(
                row, sleep_sec=sleep_sec,
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
            # mercari の連続 None → driver 再起動を試行 (anti-bot recovery)
            if (res["supplier"] == "mercari"
                    and "scraper returned None" in (res["error"] or "")):
                mercari_consec_none += 1
                if mercari_consec_none >= MERCARI_RESTART_THRESHOLD:
                    log(f"  ⚠️ mercari 連続 None {mercari_consec_none} 件 → driver 再起動を試行")
                    if mercari_driver is not None:
                        try:
                            mercari_driver.quit()
                        except Exception:
                            pass
                    try:
                        mercari_driver = create_mercari_driver(headless=True)
                        log("    ✅ mercari driver 再起動完了 (続行)")
                        mercari_consec_none = 0
                    except Exception as re:
                        log(f"    ❌ mercari driver 再起動失敗: {re} (mercari は失敗継続、他 supplier は処理する)")
                        mercari_driver = None
                        mercari_consec_none = 0  # 再起動失敗を loop しないようリセット
            if (res["error"] or "").startswith("unsupported supplier"):
                log(f"{prefix}{sup} - skip ({res['error'][:60]})")
            else:
                log(f"{prefix}{sup} ⚠️ {res['error'][:60]}")
        else:
            # 成功した supplier に対応するカウンタをリセット
            if res["supplier"] == "mercari":
                mercari_consec_none = 0
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

        # ライブ進捗通知 (callback は throttle を内部で管理)
        if progress_callback is not None:
            try:
                progress_callback(
                    phase="monitor",
                    processed=i,
                    total=total_rows,
                    errors=sum(1 for r in results if r.get("error")),
                    sheet_label=sheet_label,
                )
            except Exception:
                pass

        # Phase 9 修正: 早期 abort 廃止 (漏れ NG 原則)
        # 全 421 件処理しきる方針。mercari 不調は driver 再起動で復旧試行。

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
    # 不正 URL (unsupported supplier) を抽出して目立たせる ─ 漏れ NG 原則
    url_alerts = [
        {"row_index": r["row_index"], "url": r.get("url", ""), "error": r["error"]}
        for r in results
        if (r.get("error") or "").startswith("unsupported supplier")
    ]
    log("")
    log(f"  === 集計 [{sheet_label}] ===")
    log(f"    処理: {len(results)} / 対象 {len(rows)}")
    log(f"    新規売切: {newly_sold} / 新規復活: {newly_in_stock} / 変化なし: {len(results) - newly_sold - newly_in_stock - errors} / エラー: {errors}")
    if url_alerts:
        log(f"  ⚠️ URL 不正で在庫検出スキップ: {len(url_alerts)} 件 (スプシ修正必要)")
        for a in url_alerts[:10]:
            log(f"    row{a['row_index']:>4} {a['url'][:80]}  ← {a['error'][:60]}")
        if len(url_alerts) > 10:
            log(f"    ... +{len(url_alerts) - 10} 件")

    # 書込 (Phase 9 修正: trabajo 同等の O 列全件更新仕様)
    #   - O 列: 巡回処理した全行に時刻書込 (エラー含む)
    #   - D 列: 「変化があった行」のみ更新 (人手書込を尊重)
    #   - N 列: scrape で価格取得できた行のみ更新 (None なら触らない、purely additive)
    checked_at_now = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
    updates = []
    for r in results:
        price_jpy = r.get("price_jpy")  # None の場合 update dict には乗せない (= N 列触らない)
        if r["error"] or r["is_sold"] is None:
            # 取得不能 → O 列だけ更新 (D 列は既存維持、fail-closed 維持)
            #          N 列は price_jpy=None なので触らない (既存値維持)
            upd = {
                "row_index":  r["row_index"],
                "checked_at": checked_at_now,
                "o_only":     True,
            }
            if price_jpy is not None:
                upd["price_jpy"] = price_jpy
            updates.append(upd)
            continue
        # D 列に変化があるかどうか判定
        new_d = "○" if r["is_sold"] else ""
        old_d = (r.get("current_sold") or "").strip()
        if new_d == old_d:
            # 変化なし → O 列のみ更新 (D 列はそのまま)
            upd = {
                "row_index":  r["row_index"],
                "checked_at": checked_at_now,
                "o_only":     True,
            }
            if price_jpy is not None:
                upd["price_jpy"] = price_jpy
            updates.append(upd)
        else:
            # 変化あり → D + O 両方更新
            upd = {
                "row_index":  r["row_index"],
                "is_sold":    r["is_sold"],
                "checked_at": checked_at_now,
            }
            if price_jpy is not None:
                upd["price_jpy"] = price_jpy
            updates.append(upd)

    if dry_run:
        log("  [DRY RUN] スプシ書込 skip")
        for r in [x for x in results if x["delta"] in ("newly_sold", "newly_in_stock")][:10]:
            log(f"    変化検知サンプル: row{r['row_index']} {r['delta']} {r['url'][:50]}")
    elif updates:
        d_count = sum(1 for u in updates if not u.get("o_only"))
        n_count = sum(1 for u in updates if u.get("price_jpy") is not None)
        o_count = len(updates)
        log(f"  スプシ書込中... 全 {o_count} 行 (D 列変化 {d_count} 件 + N 列価格 {n_count} 件 + O 列 {o_count} 件)")
        try:
            res = update_listings_sold_marks(ws, updates)
            log(f"  ✅ updated={res['updated']} (d_writes={res.get('d_writes', '?')} / n_writes={res.get('n_writes', '?')} / o_writes={res.get('o_writes', '?')})")
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
        "url_alerts":     url_alerts,
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
