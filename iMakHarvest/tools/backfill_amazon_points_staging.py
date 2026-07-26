"""backfill_amazon_points_staging - 中間スプシ amazon_<label> タブの K 列に ポイント(円) を埋め戻す.

2026-07-26 user 指示: ヨドバシ tab とポイント比較できるよう、 Amazon 中間スプシにも
K=ポイント(円) を入れる (既存行は K 空だったため backfill)。

判定は scrapers.amazon_search_http.extract_points_jpy (= widget anchor 版、 backfill_amazon_points_low
と同一ソース)。 fail-closed:
  - ポイント widget が無い → K="" (盛らない)
  - fetch 失敗/captcha → その行は触らず skip (再実行で回収)
対象 = A 列が amazon.co.jp の行のみ。 K が既に入っている行は skip (再上書きしない)。

実行:
  python tools/backfill_amazon_points_staging.py --dry-run --max-rows 5
  python tools/backfill_amazon_points_staging.py
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scrapers import amazon_search  # noqa: E402
from scrapers import amazon_search_http as H  # noqa: E402
from sheet_writer_amazon import COL_POINTS, COL_PRICE, COL_URL  # noqa: E402
from sheet_writer_mercari_seller import open_seller_staging_sheet  # noqa: E402

COL_K = COL_POINTS  # 11


def _log(m: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def _cell(row, c):
    return (row[c - 1].strip() if len(row) >= c else "")


def _to_int(s):
    try:
        return int(str(s).replace(",", "").replace("¥", "").replace("￥", "").strip())
    except Exception:
        return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="gshock", help="tab suffix (= amazon_<label>)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-rows", type=int, default=0, help="処理上限 (0=無制限)")
    ap.add_argument("--overwrite", action="store_true",
                    help="K が既に入っている行も再取得して上書き (既定=空行のみ)")
    ap.add_argument("--rate-min", type=float, default=3.0)
    ap.add_argument("--rate-max", type=float, default=5.0)
    args = ap.parse_args(argv)

    sh = open_seller_staging_sheet()
    ws = sh.worksheet(f"amazon_{args.label}")
    vals = ws.get_all_values()
    _log(f"amazon_{args.label} rows={len(vals)} (header含む)")

    targets = []
    for i, row in enumerate(vals[1:], start=2):
        url = _cell(row, COL_URL)
        if "amazon.co.jp" not in url.lower():
            continue
        if not args.overwrite and _cell(row, COL_K):
            continue  # K 済 → skip
        asin = amazon_search.parse_asin_from_url(url)
        if not asin:
            continue
        targets.append((i, asin, _to_int(_cell(row, COL_PRICE))))
        if args.max_rows and len(targets) >= args.max_rows:
            break
    _log(f"対象 Amazon 行 (K空): {len(targets)}")
    if not targets:
        return 0

    session = H.create_session()
    updates = []
    stats = {"points": 0, "no_points": 0, "fetch_fail": 0}
    for idx, (ri, asin, price) in enumerate(targets, 1):
        text, captcha = H.fetch_detail_page(session, asin)
        if captcha:
            _log(f"CAPTCHA 検出 ({idx}/{len(targets)}) → 中断 (処理済 {idx-1} 件有効)")
            break
        if not text:
            stats["fetch_fail"] += 1
            _log(f"  [{idx}/{len(targets)}] row{ri} {asin}: fetch失敗 → skip")
            time.sleep(random.uniform(args.rate_min, args.rate_max))
            continue
        page_price = H.extract_price_jpy(text) or price
        points = H.extract_points_jpy(text, page_price)
        if points:
            stats["points"] += 1
            rate = f"{points / page_price * 100:.1f}%" if page_price else "-"
            _log(f"  [{idx}/{len(targets)}] row{ri} {asin}: K={points} ({rate})")
            updates.append({"range": f"K{ri}", "values": [[points]]})
        else:
            stats["no_points"] += 1
            _log(f"  [{idx}/{len(targets)}] row{ri} {asin}: ポイントなし → K=(空)")
        if idx < len(targets):
            time.sleep(random.uniform(args.rate_min, args.rate_max))

    _log(f"集計: pt取得={stats['points']} ptなし={stats['no_points']} "
         f"fetch失敗={stats['fetch_fail']} / 書込セル={len(updates)}")

    (ROOT / "debug").mkdir(exist_ok=True)
    (ROOT / "debug" / "backfill_amazon_points_staging.json").write_text(
        json.dumps({"dry_run": args.dry_run, "stats": stats,
                    "updates": len(updates)}, ensure_ascii=False, indent=2),
        encoding="utf-8")

    if args.dry_run:
        _log("dry-run: 書込なし")
        return 0
    if not updates:
        _log("書込対象なし")
        return 0
    # DNS flapping 耐性 (= 2026-07 環境で getaddrinfo 断続失敗、 backfill 完走後の書込で全落ち
    # した事故対策)。 chunk 毎に backoff リトライして 収集済ポイントを取りこぼさない。
    CH = 60
    written = 0
    for i in range(0, len(updates), CH):
        chunk = updates[i:i + CH]
        for att in range(1, 6):
            try:
                ws.batch_update(chunk, value_input_option="USER_ENTERED")
                written += len(chunk)
                break
            except Exception as e:  # noqa: BLE001
                _log(f"  書込 retry {att}/5 ({type(e).__name__}) → backoff")
                time.sleep(5 * att)
        else:
            _log(f"❌ 書込不能 (DNS?) — {written} セル書込済、 残 {len(updates) - written} は未書込")
            return 1
    _log(f"書込完了: {written} セル")
    return 0


if __name__ == "__main__":
    sys.exit(main())
