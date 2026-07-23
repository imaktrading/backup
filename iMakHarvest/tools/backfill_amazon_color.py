"""backfill_amazon_color - Amazon 既存 entry の S 列 (色) を後付け backfill.

Phase 1c-color (commit f0d730c) 以前にスプシに書込まれた Amazon 行は S 列空欄。
このスクリプトは指定フィルタに合致する Amazon 行を抽出し、現行 fetch_detail で
色を再判定 → S 列のみ update する idempotent な one-off ツール。

使い方:
    # 事前カウント (AI 呼ばず、件数 + コスト見積もりのみ)
    python tools/backfill_amazon_color.py --count-only --category G-shock

    # dry-run 10 件 (実 AI 呼出、スプシ書込なし)
    python tools/backfill_amazon_color.py --category G-shock --dry-run --max-items 10

    # 本実行 (全件、スプシ S 列に書込)
    python tools/backfill_amazon_color.py --category G-shock

挙動:
  1. HIGH/LOW 両スプシをスキャン
  2. R 列 (col 18) が --category 一致 + A 列 (URL) が amazon.co.jp/dp/ パターン
     + S 列 (col 19) が空欄 の行を対象に抽出
  3. --count-only: 件数と AI コスト見積もりだけ表示して終了
  4. --dry-run: 対象先頭 N 件を fetch して S 列予定値を log 表示 (スプシ未書込)
  5. 通常: 各対象行を fetch → S 列だけ batch_update (B/C/D/E/F/G/H, I-R, T は touch なし)

idempotent: 既に S 列に値ある行は対象に含めない。再実行で AI 二重コスト発生しない。
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scrapers import amazon_item_detail, amazon_wishlist  # noqa: E402
from sheet_writer import (  # noqa: E402
    COL_COLOR,
    COL_URL,
    HIGH_SHEET_ID,
    LISTINGS_GID,
    LOW_SHEET_ID,
    get_listings_worksheet,
    open_sheet_by_id,
)


# R 列 = カテゴリ列 (1-based 18)
COL_CATEGORY = 18

# AI コスト見積もり (Claude Haiku Vision、2026-05-13 実勢)
COST_PER_AI_CALL_USD = 0.001
SEC_PER_ITEM = 6.0  # Amazon detail fetch (~6 sec/item 実測)


def _log(msg: str) -> None:
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}")


def _col_letter(col_1based: int) -> str:
    s = ""
    n = col_1based
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _is_amazon_url(url: str) -> bool:
    """A 列 URL が Amazon パターンか判定."""
    if not url:
        return False
    return "amazon.co.jp/dp/" in url or "amazon.co.jp/gp/product/" in url


def _scan_sheet(sheet_label: str, sheet_id: str, category: str) -> list[tuple[str, int, str]]:
    """1 つのスプシをスキャン、対象行を [(sheet_label, row_idx, url), ...] で返却."""
    _log(f"  {sheet_label} スプシ open: sheet_id={sheet_id[:14]}..")
    sh = open_sheet_by_id(sheet_id)
    ws = get_listings_worksheet(sh, gid=LISTINGS_GID)
    all_values = ws.get_all_values()
    _log(f"    全行数: {len(all_values)}")

    targets: list[tuple[str, int, str]] = []
    cat_matched = 0
    amazon_matched = 0
    s_empty_matched = 0

    for idx, row in enumerate(all_values, start=1):
        # ヘッダー行 skip
        if idx == 1:
            continue
        if not row:
            continue
        # R 列カテゴリ
        cat = (row[COL_CATEGORY - 1] if len(row) >= COL_CATEGORY else "") or ""
        if cat.strip() != category:
            continue
        cat_matched += 1
        # A 列 URL = Amazon
        url = (row[COL_URL - 1] if len(row) >= COL_URL else "") or ""
        url = url.strip()
        if not _is_amazon_url(url):
            continue
        amazon_matched += 1
        # S 列空欄
        s_val = (row[COL_COLOR - 1] if len(row) >= COL_COLOR else "") or ""
        if s_val.strip():
            continue
        s_empty_matched += 1
        targets.append((sheet_label, idx, url))

    _log(f"    R 列='{category}': {cat_matched} 件 / うち Amazon URL: {amazon_matched} 件 "
         f"/ うち S 列空欄: {s_empty_matched} 件 = backfill 対象")
    return targets


def _estimate_cost(n: int) -> tuple[float, float]:
    """対象 N 件の (推定 AI コスト USD, 推定所要時間 分) を返す."""
    usd = n * COST_PER_AI_CALL_USD
    sec = n * SEC_PER_ITEM
    return usd, sec / 60.0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--category", default="G-shock",
                    help="R 列カテゴリフィルタ (default: G-shock)")
    ap.add_argument("--count-only", action="store_true",
                    help="件数 + コスト見積もりのみ (AI 呼ばず、スプシ書込なし)")
    ap.add_argument("--dry-run", action="store_true",
                    help="AI は呼ぶがスプシ書込はしない (動作確認用)")
    ap.add_argument("--max-items", type=int, default=None,
                    help="処理上限 (dry-run 用)")
    ap.add_argument("--sheet", choices=["high", "low", "both"], default="both")
    args = ap.parse_args(argv)

    _log(f"=== Amazon 色 backfill: category={args.category!r} ===")
    _log(f"  mode: count-only={args.count_only}, dry-run={args.dry_run}, "
         f"max-items={args.max_items}, sheet={args.sheet}")

    # 両スプシスキャン
    all_targets: list[tuple[str, int, str]] = []
    if args.sheet in ("high", "both"):
        all_targets.extend(_scan_sheet("HIGH", HIGH_SHEET_ID, args.category))
    if args.sheet in ("low", "both"):
        all_targets.extend(_scan_sheet("LOW", LOW_SHEET_ID, args.category))

    n = len(all_targets)
    usd, mins = _estimate_cost(n)
    _log("")
    _log(f"=== 集計 ===")
    _log(f"  backfill 対象合計: {n} 件")
    _log(f"  推定 AI コスト   : ${usd:.3f} (¥{usd*150:.0f} @ 150円/USD)")
    _log(f"  推定所要時間     : {mins:.1f} 分 (1 件 ~{SEC_PER_ITEM:.0f}秒)")
    _log("")

    if args.count_only:
        # 先頭 5 件サンプル表示 (動作確認用)
        if all_targets:
            _log("=== 先頭 5 件 サンプル ===")
            for sl, row_idx, url in all_targets[:5]:
                _log(f"  {sl} row {row_idx}: {url}")
        _log("count-only モード終了。実行するには --count-only を外して再実行。")
        return 0

    if not all_targets:
        _log("対象なし、終了")
        return 0

    # 処理上限適用
    if args.max_items and args.max_items < n:
        all_targets = all_targets[: args.max_items]
        _log(f"  --max-items {args.max_items} で先頭のみ処理")

    # Selenium driver 起動
    _log("Amazon driver 起動 (visible)...")
    driver = amazon_wishlist.create_driver(headless=False)

    updates: dict[str, list[tuple[int, str, str]]] = {"HIGH": [], "LOW": []}
    # (row_idx, new_color, status)
    failures: list[tuple[str, int, str, str]] = []
    # (sheet_label, row_idx, url, reason)

    try:
        for i, (sl, row_idx, url) in enumerate(all_targets, start=1):
            _log(f"  [{i}/{len(all_targets)}] {sl} row={row_idx} fetch: {url}")
            try:
                detail = amazon_item_detail.fetch_detail(driver, url)
            except Exception as e:
                _log(f"           ❌ fetch 例外: {type(e).__name__}: {e}")
                failures.append((sl, row_idx, url, f"exception: {type(e).__name__}"))
                continue
            if detail is None:
                _log(f"           ❌ DOM 解析不能, skip")
                failures.append((sl, row_idx, url, "fetch_detail returned None"))
                continue
            status = detail.get("status", "UNKNOWN")
            new_color = detail.get("color", "") or ""
            _log(f"           color: {new_color!r}, status: {status}")
            updates[sl].append((row_idx, new_color, status))
            time.sleep(1.0)  # rate limit
    finally:
        try:
            driver.quit()
        except Exception:
            pass

    # 統計
    total_updates = sum(len(v) for v in updates.values())
    color_filled = sum(1 for sl_updates in updates.values() for _, c, _ in sl_updates if c)
    color_empty = total_updates - color_filled
    _log("")
    _log(f"=== 取得結果 ===")
    _log(f"  fetch 成功      : {total_updates}/{len(all_targets)} 件")
    _log(f"  color 埋まり     : {color_filled} 件")
    _log(f"  color 空欄 (AI 不明等): {color_empty} 件")
    _log(f"  fetch 失敗      : {len(failures)} 件")

    if args.dry_run:
        _log("dry-run モード: スプシ書込スキップ。実行するには --dry-run を外して再実行。")
        return 0

    if total_updates == 0:
        _log("更新対象なし、終了")
        return 0

    # スプシ S 列のみ batch_update
    s_col = _col_letter(COL_COLOR)
    for sl in ("HIGH", "LOW"):
        rows_data = updates[sl]
        if not rows_data:
            continue
        sheet_id = HIGH_SHEET_ID if sl == "HIGH" else LOW_SHEET_ID
        sh = open_sheet_by_id(sheet_id)
        ws = get_listings_worksheet(sh, gid=LISTINGS_GID)
        batch_data = [
            {"range": f"{s_col}{row}", "values": [[color]]}
            for row, color, _ in rows_data
        ]
        _log(f"  {sl}: S 列 batch_update {len(batch_data)} 行...")
        try:
            ws.batch_update(batch_data, value_input_option="USER_ENTERED")
            _log(f"  {sl}: ✅ 完了")
        except Exception as e:
            _log(f"  {sl}: ❌ batch_update 例外: {e}")
            return 1

    _log(f"\n=== backfill 完了 ===")
    _log(f"  全対象       : {len(all_targets)}")
    _log(f"  fetch 成功    : {total_updates}")
    _log(f"  color 埋まり   : {color_filled}")
    _log(f"  S 列残空欄     : {color_empty + len(failures)} 件 (= 全対象 - color 埋まり)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
