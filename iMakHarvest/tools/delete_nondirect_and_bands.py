"""中間スプシ amazon_gshock から 非直販 + バンド類 を物理削除.

2026-06-12 user 指示: 非直販 (Q='非直販') と バンド類(アクセサリ、時計でない) を sheet から削除。

安全策:
  - 非直販の「時計」行は削除直前に merchantId 再確認 (= buybox rotation で直販に戻っていれば
    削除せず Q クリア。 誤って直販品を消さない)。
  - バンド類 (= 替え/オプションバンド) は seller によらず削除 (= watch sheet スコープ外)。
  - 削除は row index 降順 (= 上の削除で下の index がズレない)。

実行:
  python tools/delete_nondirect_and_bands.py --dry-run
  python tools/delete_nondirect_and_bands.py
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scrapers import amazon_search_http  # noqa: E402
from sheet_writer_mercari_seller import open_seller_staging_sheet  # noqa: E402

TAB_NAME = "amazon_gshock"
COL_URL = 1
COL_TITLE = 3
COL_FLG = 17
FLG_EXCLUDE = "非直販"

_BAND_RE = re.compile(r"替えバンド|オプションバンド|オプショナルバンド|交換用バンド|ベルト")


def _cell(row, c):
    return (row[c - 1].strip() if len(row) >= c else "")


def _asin(url):
    m = re.search(r"/(?:dp|gp/product)/([A-Z0-9]{10})", url, re.IGNORECASE)
    return m.group(1).upper() if m else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    sh = open_seller_staging_sheet()
    ws = sh.worksheet(TAB_NAME)
    vals = ws.get_all_values()

    band_rows, nondirect_watch_rows = [], []
    for i, row in enumerate(vals[1:], start=2):
        if not row or not _cell(row, COL_URL):
            continue
        title = _cell(row, COL_TITLE)
        flg = _cell(row, COL_FLG)
        is_band = bool(_BAND_RE.search(title))
        if is_band:
            band_rows.append({"row": i, "asin": _asin(_cell(row, COL_URL)), "title": title[:45]})
        elif flg == FLG_EXCLUDE:
            nondirect_watch_rows.append({"row": i, "asin": _asin(_cell(row, COL_URL)), "title": title[:45]})

    # 非直販時計を再確認 (= rotation 対策)
    session = amazon_search_http.create_session()
    to_delete_nondirect, reverted_to_direct = [], []
    for t in nondirect_watch_rows:
        text, captcha = amazon_search_http.fetch_detail_page(session, t["asin"])
        if captcha:
            print("[delete] CAPTCHA、 中断", flush=True)
            return 1
        direct = bool(text) and amazon_search_http.SELLER_AMAZON_PRIMARY_MARKER in text
        if direct:
            reverted_to_direct.append(t)
        else:
            to_delete_nondirect.append(t)
        time.sleep(random.uniform(2.0, 3.5))

    delete_targets = band_rows + to_delete_nondirect
    delete_rows_idx = sorted({t["row"] for t in delete_targets}, reverse=True)

    print(f"\n[delete] band={len(band_rows)} nondirect_watch={len(nondirect_watch_rows)} "
          f"(削除={len(to_delete_nondirect)} / 直販復帰={len(reverted_to_direct)})", flush=True)
    print(f"[delete] 削除対象 行数: {len(delete_rows_idx)} (dry_run={args.dry_run})", flush=True)
    for t in sorted(delete_targets, key=lambda x: x["row"]):
        kind = "BAND" if t in band_rows else "非直販"
        print(f"  row{t['row']} [{kind}] {t['asin']} | {t['title']}", flush=True)
    if reverted_to_direct:
        print("  --- rotation で直販復帰 → 削除せず Q クリア ---", flush=True)
        for t in reverted_to_direct:
            print(f"  row{t['row']} {t['asin']} | {t['title']}", flush=True)

    deleted = 0
    cleared = 0
    if not args.dry_run:
        # 直販復帰行の Q クリア (= 削除より先、 index 変わらないうちに)
        for t in reverted_to_direct:
            try:
                ws.update_cell(t["row"], COL_FLG, "")
                cleared += 1
                time.sleep(0.5)
            except Exception as e:
                print(f"  WARN clear row {t['row']}: {e!r}", flush=True)
        # 削除 (= 降順)
        for r in delete_rows_idx:
            try:
                ws.delete_rows(r)
                deleted += 1
                time.sleep(0.6)
            except Exception as e:
                print(f"  WARN delete row {r}: {e!r}", flush=True)

    print(f"\n[delete] deleted={deleted} cleared_q={cleared}", flush=True)
    out = {
        "dry_run": args.dry_run,
        "band_rows": band_rows,
        "nondirect_deleted": to_delete_nondirect,
        "reverted_to_direct": reverted_to_direct,
        "delete_rows_idx": delete_rows_idx,
        "deleted": deleted,
        "cleared_q": cleared,
    }
    (ROOT / "debug" / "delete_nondirect_bands_result.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
