"""backfill_amazon_points_low - LOW の Amazon 行に K=ポイント(円) / N=実質仕入値(F−K) を記入.

HQ 依頼 2026-07-22 (Amazon ポイント込み実質仕入値)。 ユーザー確定仕様:
  - K列(11) = ポイント(円)  ※ LOW K は未使用確認済 (HQ/Harvest/監視くん とも)。
    ヘッダ「NO-GO判定」→「ポイント(円)」に改名 (apply 時)。
  - N列(14) = F − K  (下流 pick_cost_jpy が N>F 優先で読む = 下流変更ゼロ)
  - 対象 = A列 が amazon.co.jp の行のみ (メルカリ等は不触)。 D=○(売切) は既定 skip。
  - fail-closed:
      * ページにポイント表記なし → K="" / N=F  (値引きを盛らない)
      * fetch 失敗/captcha → 行を触らず skip (再実行で埋まる。 過小 N を書かない)
      * ポイントは「確実に付く基本分」のみ (= extract_points_jpy が price×pct 整合で
        campaign 分を排除)
  - 価格乖離対策: シート F と現ページ価格が違う行は F/K/N を **現在ページ値で一貫更新**
    (旧F−現pt の混成は価格上昇時に N 過小 = 原価過小の危険があるため)。

使い方:
  python tools/backfill_amazon_points_low.py --dry-run --max-rows 5   # 検証
  python tools/backfill_amazon_points_low.py                          # 本適用
"""
from __future__ import annotations

import argparse
import random
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scrapers import amazon_search  # noqa: E402
from scrapers import amazon_search_http as H  # noqa: E402
from sheet_writer import (  # noqa: E402
    LISTINGS_GID,
    LOW_SHEET_ID,
    get_listings_worksheet,
    open_sheet_by_id,
)

COL_A_URL = 1
COL_D_SOLD = 4
COL_F_PRICE = 6
COL_K_POINTS = 11
COL_N_NET = 14
K_HEADER = "ポイント(円)"


def _log(m: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def _cell(row: list, col: int) -> str:
    return (row[col - 1] if len(row) >= col else "").strip()


def _to_int(s: str):
    try:
        return int(str(s).replace(",", "").replace("¥", "").strip())
    except Exception:
        return None


def plan_row(sheet_f, page_price, points):
    """1 行の書込計画 (= 純粋関数、 テスト対象).

    Returns: {"f": int|None(変更なし), "k": int|"", "n": int} or None (= skip)
    """
    if page_price is None:
        return None  # fetch 失敗系: 触らない (fail-closed)
    k = points if points else ""
    n = page_price - points if points else page_price
    f_update = page_price if (sheet_f is None or page_price != sheet_f) else None
    return {"f": f_update, "k": k, "n": n}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--include-sold", action="store_true", help="D=○ 行も対象に含める")
    ap.add_argument("--max-rows", type=int, default=0, help="処理上限 (0=無制限、検証用)")
    ap.add_argument("--rate-min", type=float, default=3.0)
    ap.add_argument("--rate-max", type=float, default=5.0)
    args = ap.parse_args(argv)

    # DNS flapping 耐性 (= 2026-07 環境で getaddrinfo 断続失敗) → backoff リトライ
    sh = None
    last = None
    for att in range(1, 5):
        try:
            sh = open_sheet_by_id(LOW_SHEET_ID)
            break
        except Exception as e:  # noqa: BLE001
            last = e
            _log(f"LOW open 失敗 (attempt {att}/4): {type(e).__name__} → backoff")
            time.sleep(6 * att)
    if sh is None:
        _log(f"LOW open 不能 (DNS?): {last!r} → 中断")
        return 1
    ws = get_listings_worksheet(sh, LISTINGS_GID)
    vals = ws.get_all_values()
    _log(f"LOW rows={len(vals)} (header含む)")

    # 対象行の選定
    targets = []
    skipped_sold = 0
    for i, row in enumerate(vals[1:], start=2):
        url = _cell(row, COL_A_URL)
        if "amazon.co.jp" not in url.lower():
            continue
        if not args.include_sold and _cell(row, COL_D_SOLD) == "○":
            skipped_sold += 1
            continue
        asin = amazon_search.parse_asin_from_url(url)
        if not asin:
            continue
        targets.append((i, asin, _to_int(_cell(row, COL_F_PRICE))))
        if args.max_rows and len(targets) >= args.max_rows:
            break
    _log(f"対象 Amazon 行: {len(targets)} (売切skip={skipped_sold}, include_sold={args.include_sold})")
    if not targets:
        return 0

    session = H.create_session()
    updates = []
    stats = {"points": 0, "no_points": 0, "fetch_fail": 0, "f_refresh": 0}
    for idx, (ri, asin, sheet_f) in enumerate(targets, 1):
        text, captcha = H.fetch_detail_page(session, asin)
        if captcha:
            _log(f"CAPTCHA 検出 ({idx}/{len(targets)}) → 中断 (処理済 {idx-1} 件は有効)")
            break
        if not text:
            stats["fetch_fail"] += 1
            _log(f"  [{idx}/{len(targets)}] row{ri} {asin}: fetch失敗 → skip (再実行で回収)")
            time.sleep(random.uniform(args.rate_min, args.rate_max))
            continue
        page_price = H.extract_price_jpy(text)
        points = H.extract_points_jpy(text, page_price)
        plan = plan_row(sheet_f, page_price, points)
        if plan is None:
            stats["fetch_fail"] += 1
            _log(f"  [{idx}/{len(targets)}] row{ri} {asin}: 価格取得不能 → skip")
        else:
            tag = "pt" if points else "ptなし"
            stats["points" if points else "no_points"] += 1
            f_note = ""
            if plan["f"] is not None and sheet_f is not None:
                stats["f_refresh"] += 1
                f_note = f", F更新 {sheet_f}→{page_price}"
            k_disp = plan["k"] if plan["k"] != "" else "(空)"
            _log(f"  [{idx}/{len(targets)}] row{ri} {asin}: F={page_price} K={k_disp} "
                 f"N={plan['n']} ({tag}{f_note})")
            if plan["f"] is not None:
                updates.append({"range": f"F{ri}", "values": [[plan["f"]]]})
            updates.append({"range": f"K{ri}", "values": [[plan["k"]]]})
            updates.append({"range": f"N{ri}", "values": [[plan["n"]]]})
        if idx < len(targets):
            time.sleep(random.uniform(args.rate_min, args.rate_max))

    _log(f"集計: pt取得={stats['points']} ptなし={stats['no_points']} "
         f"fetch失敗={stats['fetch_fail']} F現在化={stats['f_refresh']} / 書込セル={len(updates)}")

    if args.dry_run:
        _log("dry-run: 書込なし")
        return 0
    if not updates:
        _log("書込対象なし")
        return 0

    # K1 ヘッダ改名 (= 「NO-GO判定」等 → 「ポイント(円)」)
    cur_hdr = _cell(vals[0], COL_K_POINTS) if vals else ""
    if cur_hdr != K_HEADER:
        ws.update_cell(1, COL_K_POINTS, K_HEADER)
        _log(f"K1 ヘッダ: {cur_hdr!r} → {K_HEADER!r}")

    # chunk 書込
    CH = 60
    for i in range(0, len(updates), CH):
        ws.batch_update(updates[i:i + CH], value_input_option="USER_ENTERED")
    _log(f"書込完了: {len(updates)} セル")
    return 0


if __name__ == "__main__":
    sys.exit(main())
