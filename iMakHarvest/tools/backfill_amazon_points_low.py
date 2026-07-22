"""backfill_amazon_points_low - LOW の Amazon 行に K=ポイント(円) を記入.

HQ 依頼 2026-07-22 + **設計変更 (同日 formula_switch)**:
  - 書き手はスプシに**観測値のみ**書く。 K列(11) = ポイント(円) を本 tool が記入。
  - **N列は書かない** (= HQ が ARRAYFORMULA `=(MあればM、なければF)−K` を設置。
    N セルへの値書込は関数を壊すため、 1 プロセスも残さないこと)。
  - **F の追従更新もしない** (= F は capture 時価格として不変。 価格鮮度は監視くんの M が担う)。
  - ※ 初回適用 (2026-07-22 run) のみ旧仕様で N=F−K / F現在化 を書いたが、 HQ の関数化で
    置換されるため無害 (= formula_switch 依頼書 3 項で完走 OK 済)。
  - fail-closed:
      * ページにポイント表記なし → K=""  (値引きを盛らない)
      * fetch 失敗/captcha → 行を触らず skip (再実行で埋まる)
      * ポイントは「確実に付く基本分」のみ (= extract_points_jpy が price×pct 整合で
        campaign 分を排除)
  - 対象 = A列 が amazon.co.jp の行のみ (メルカリ等は不触)。 D=○(売切) は既定 skip。

使い方:
  python tools/backfill_amazon_points_low.py --dry-run --max-rows 5   # 検証
  python tools/backfill_amazon_points_low.py                          # 本適用 (K のみ)
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
# COL_N (14) は formula_switch (2026-07-22) 以降 書込禁止 (= HQ の ARRAYFORMULA が計算)
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

    formula_switch (2026-07-22) 後: **K のみ書く** (N はシート関数、 F は不変)。
    Returns: {"k": int|""} or None (= fetch 失敗系: 触らない fail-closed)
    """
    if page_price is None:
        return None  # fetch 失敗系: 触らない (fail-closed)
    return {"k": points if points else ""}


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
    stats = {"points": 0, "no_points": 0, "fetch_fail": 0}
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
            k_disp = plan["k"] if plan["k"] != "" else "(空)"
            _log(f"  [{idx}/{len(targets)}] row{ri} {asin}: page価格={page_price} "
                 f"K={k_disp} ({tag})  ※N/Fは書かない(関数化後)")
            updates.append({"range": f"K{ri}", "values": [[plan["k"]]]})
        if idx < len(targets):
            time.sleep(random.uniform(args.rate_min, args.rate_max))

    _log(f"集計: pt取得={stats['points']} ptなし={stats['no_points']} "
         f"fetch失敗={stats['fetch_fail']} / 書込セル(K)={len(updates)}")

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
