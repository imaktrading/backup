"""中間スプシ amazon_gshock → LOW シートへ 重複しない分だけ転記.

2026-06-12 user 指示: staging の G-shock 309件のうち、 LOW に未登録の分を LOW に追記。
重複判定は **ASIN** (= URL から抽出)。 LOW は Amazon URL を wishlist 形式
(`/dp/ASIN/?coliid=...&ref_=list_c_wl_...`) で持つため URL 完全一致は不可
(= 同一 ASIN を二重登録してしまう)。

- staging / LOW とも同じ「商品管理シート」 37 列フォーマット → 行をそのままコピー。
- B列(eBay item ID)/D列(売切flag) は空欄のまま (= 新規 listing 候補として正)。

実行:
  python tools/transfer_amazon_gshock_to_low.py --dry-run
  python tools/transfer_amazon_gshock_to_low.py
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import gspread  # noqa: E402
from google.oauth2.service_account import Credentials  # noqa: E402

from sheet_writer import CREDS_PATH, SCOPES, LOW_SHEET_ID, LISTINGS_GID  # noqa: E402
from sheet_writer_mercari_seller import open_seller_staging_sheet  # noqa: E402

STAGING_TAB = "amazon_gshock"
COL_URL = 1


def _asin(url: str) -> str | None:
    m = re.search(r"/dp/([A-Z0-9]{10})", url or "", re.I)
    return m.group(1).upper() if m else None


def _open_low_ws():
    creds = Credentials.from_service_account_file(CREDS_PATH, scopes=SCOPES)
    gc = gspread.authorize(creds)
    low = gc.open_by_key(LOW_SHEET_ID)
    for w in low.worksheets():
        if w.id == LISTINGS_GID:
            return w
    raise RuntimeError(f"LOW gid={LISTINGS_GID} worksheet not found")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    sh = open_seller_staging_sheet()
    ws = sh.worksheet(STAGING_TAB)
    sv = ws.get_all_values()
    ncols = len(sv[0]) if sv else 37
    src = [r for r in sv[1:] if r and (r[COL_URL - 1] or "").strip()]
    print(f"[transfer] staging {STAGING_TAB}: {len(src)} 行 (cols={ncols})", flush=True)

    lws = _open_low_ws()
    lv = lws.get_all_values()
    low_rows = [r for r in lv[1:] if r and (r[COL_URL - 1] or "").strip()]
    low_asins = {a for a in (_asin(r[COL_URL - 1]) for r in low_rows) if a}
    print(f"[transfer] LOW '{lws.title}': 既存 {len(low_rows)} 行 / Amazon ASIN {len(low_asins)} 種", flush=True)

    # ASIN dedup
    to_append, skipped_dup, no_asin = [], 0, 0
    seen_batch = set()
    for r in src:
        a = _asin(r[COL_URL - 1])
        if not a:
            no_asin += 1
            continue
        if a in low_asins or a in seen_batch:
            skipped_dup += 1
            continue
        seen_batch.add(a)
        # 行を LOW 列数に揃える (= 37 列、 不足分は空欄 padding)
        row = list(r[:ncols]) + [""] * max(0, ncols - len(r))
        to_append.append(row[:ncols])

    print(f"[transfer] 追記対象 (ASIN新規): {len(to_append)} / "
          f"既存dup skip: {skipped_dup} / ASIN無し skip: {no_asin}", flush=True)

    appended = 0
    if to_append and not args.dry_run:
        lws.append_rows(to_append, value_input_option="USER_ENTERED")
        appended = len(to_append)
        print(f"[transfer] LOW へ {appended} 行 append 完了", flush=True)

    out = {
        "dry_run": args.dry_run,
        "staging_rows": len(src),
        "low_existing": len(low_rows),
        "low_asins": len(low_asins),
        "to_append": len(to_append),
        "skipped_dup": skipped_dup,
        "no_asin": no_asin,
        "appended": appended,
        "append_asins": [_asin(r[COL_URL - 1]) for r in to_append],
    }
    (ROOT / "debug" / "transfer_low_result.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[transfer] summary: {ROOT / 'debug' / 'transfer_low_result.json'}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
