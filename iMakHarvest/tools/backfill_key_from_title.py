"""中間スプシ amazon_gshock の空欄 KEY(AI列) を title から backfill.

2026-06-12: KEY 空欄 12件の是正。 型番が日本語直結で抽出漏れしていた title を
修正済 _extract_product_id_estimated_from_title で再抽出して埋める。

対象: KEY 空欄 かつ Q!='非直販' (= keep 行) のみ。 非直販(除外)は対象外。
バンド類 (= 型番が watch 型番でない) は抽出 "" になり空欄のまま (= 後で報告)。
Amazon fetch なし (= title は既にスプシにある)。

実行:
  python tools/backfill_key_from_title.py --dry-run
  python tools/backfill_key_from_title.py
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scrapers.amazon_item_detail import _extract_product_id_estimated_from_title  # noqa: E402
from sheet_writer_mercari_seller import open_seller_staging_sheet  # noqa: E402

TAB_NAME = "amazon_gshock"
COL_URL = 1   # A
COL_TITLE = 3  # C
COL_FLG = 17  # Q
COL_KEY = 35  # AI
FLG_EXCLUDE = "非直販"


def _cell(row, c):
    return (row[c - 1].strip() if len(row) >= c else "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    sh = open_seller_staging_sheet()
    ws = sh.worksheet(TAB_NAME)
    vals = ws.get_all_values()

    filled, still_empty, skipped_excluded = [], [], []
    for i, row in enumerate(vals[1:], start=2):
        if not row:
            continue
        if not _cell(row, COL_URL):
            continue
        if _cell(row, COL_KEY):
            continue  # 既に KEY あり
        flg = _cell(row, COL_FLG)
        title = _cell(row, COL_TITLE)
        if flg == FLG_EXCLUDE:
            skipped_excluded.append({"row": i, "title": title[:50]})
            continue
        key = _extract_product_id_estimated_from_title(title)
        if key:
            filled.append({"row": i, "key": key, "title": title[:50]})
        else:
            still_empty.append({"row": i, "title": title[:50]})

    print(f"[backfill] 空欄KEY keep行: fill={len(filled)} still_empty={len(still_empty)} "
          f"skipped_excluded={len(skipped_excluded)} (dry_run={args.dry_run})", flush=True)
    for f in filled:
        print(f"  row{f['row']} KEY='{f['key']}' <- {f['title']}", flush=True)
    print("  --- 抽出できず空欄のまま (= バンド類/型番無し、 要確認) ---", flush=True)
    for s in still_empty:
        print(f"  row{s['row']} : {s['title']}", flush=True)

    done = 0
    if filled and not args.dry_run:
        for f in filled:
            try:
                ws.update_cell(f["row"], COL_KEY, f["key"])
                done += 1
                time.sleep(0.5)
            except Exception as e:
                print(f"  WARN row {f['row']} 書込失敗: {e!r}", flush=True)
    print(f"[backfill] written={done}", flush=True)

    out = {
        "dry_run": args.dry_run,
        "filled": filled,
        "still_empty": still_empty,
        "skipped_excluded": skipped_excluded,
        "written": done,
    }
    (ROOT / "debug" / "backfill_key_result.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
