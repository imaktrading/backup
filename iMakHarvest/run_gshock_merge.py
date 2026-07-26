"""run_gshock_merge - G-shock 商品管理シート(LOW=1jF9vggb)の AC-AG 補URL に
                     ヨドバシURL を型番キーで冪等追記する実運用配線 (2026-07-26 本実装).

HQ 依頼 `..._gshock_yodobashi_impl_go.md` 分界:
  - Harvest = 補URL(データ)を AC-AG に冪等追記まで (= 本ツール)。**D列(在庫状態)は touch しない**。
  - Inventory = D=○復活 / M=min(在庫あり 主+補) の状態書換。

初弾 = 取下げAmazon ∩ ヨドバシ在庫 21型番 (`_amazon_jp_dumps/yodobashi_rescue_candidates.json`)。
同一型番が LOW 複数行に在る場合は **該当全行**に冪等追記 (補URLはデータ、行毎に独立)。

冪等性 = gshock_merge.compute_merge (空枠のみ・満杯skip・既存/主URL重複skip)。

使い方:
  python run_gshock_merge.py --dry-run                      # 書込計画のみ (21型番救済)
  python run_gshock_merge.py                                # AC-AG 実書込
  python run_gshock_merge.py --source <json>               # 別の {model,url} list を投入
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from gshock_merge import compute_merge  # noqa: E402
from scrapers.yodobashi_search_http import extract_model_from_title  # noqa: E402
from sheet_writer_amazon import (  # noqa: E402
    LISTINGS_GID,
    LOW_SHEET_ID,
    get_listings_worksheet,
    open_sheet_by_id,
)

COL_URL = 1        # A
COL_D = 4          # D 売切 (= 絶対 touch しない)
COL_SUPP_START = 29  # AC
COL_SUPP_END = 33    # AG (補URL 1-5)
COL_KEY = 35       # AI 型番
RESCUE_JSON = Path(r"c:\dev\iMak_data\catalog\_amazon_jp_dumps\yodobashi_rescue_candidates.json")


def _log(m: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def _col_letter(col: int) -> str:
    s = ""
    while col > 0:
        col, r = divmod(col - 1, 26)
        s = chr(65 + r) + s
    return s


def _cell(row, c):
    return (row[c - 1].strip() if len(row) >= c else "")


def _row_model(row) -> str:
    return (_cell(row, COL_KEY) or extract_model_from_title(_cell(row, 3))).upper()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--source", default=str(RESCUE_JSON),
                    help="投入する {model,url} list の JSON (既定=21型番救済)")
    args = ap.parse_args(argv)

    src = json.loads(Path(args.source).read_text(encoding="utf-8"))
    # {model(大文字): url} (同型番複数URLは最初の1つ=ヨドバシ想定)
    model_url = {}
    for x in src:
        m = (x.get("model") or "").upper()
        u = (x.get("url") or "").strip()
        if m and u and m not in model_url:
            model_url[m] = u
    _log(f"投入型番: {len(model_url)} (source={Path(args.source).name})")

    ws = get_listings_worksheet(open_sheet_by_id(LOW_SHEET_ID), LISTINGS_GID)
    vals = ws.get_all_values()
    _log(f"LOW 総行: {len(vals)}")

    # 行単位で existing_by_key を構築 (キー = 行番号、 同型番複数行を独立に扱う)
    existing_by_key: dict[str, dict] = {}
    row_meta: dict[str, dict] = {}          # rowkey -> {rownum, model, empty_cols[list]}
    new_items: list[dict] = []
    for i, row in enumerate(vals[1:], start=2):
        model = _row_model(row)
        if model not in model_url:
            continue
        supp = [_cell(row, c) for c in range(COL_SUPP_START, COL_SUPP_END + 1)]
        supp_urls = [s for s in supp if s]
        empty_cols = [c for c in range(COL_SUPP_START, COL_SUPP_END + 1)
                      if not _cell(row, c)]
        rk = str(i)
        existing_by_key[rk] = {"primary_url": _cell(row, COL_URL), "supp_urls": supp_urls}
        row_meta[rk] = {"rownum": i, "model": model, "empty_cols": empty_cols}
        new_items.append({"model": rk, "url": model_url[model], "source": "yodobashi"})

    _log(f"該当行 (投入型番に一致): {len(existing_by_key)}")
    if not existing_by_key:
        _log("該当行なし")
        return 0

    plan = compute_merge(existing_by_key, new_items)
    _log(f"compute_merge: 追記対象行={len(plan['supp_additions'])} "
         f"冪等skip(既存)={plan['skipped_dup']} 満杯skip={plan['skipped_full']} "
         f"新規候補={len(plan['new_candidates'])}")

    # rowkey -> AC-AG セル書込 (空枠に順に)
    updates = []
    for rk, urls in plan["supp_additions"].items():
        meta = row_meta[rk]
        empty = meta["empty_cols"]
        for j, u in enumerate(urls):
            if j >= len(empty):
                break  # 空枠不足 (compute_merge が満杯skipするので通常来ない)
            col = empty[j]
            cell = f"{_col_letter(col)}{meta['rownum']}"
            updates.append({"range": cell, "values": [[u]]})
            _log(f"  row{meta['rownum']} {meta['model']:16} {cell} <- {u[-32:]}")

    _log(f"書込計画: {len(updates)} セル (AC-AG のみ、 D列 不触)")
    if args.dry_run:
        _log("dry-run: 書込なし")
        return 0
    if not updates:
        _log("書込対象なし")
        return 0
    # 安全弁: 書込先は AC-AG 列のみ (D=在庫状態 等を絶対に触らない)
    allowed = {_col_letter(c) for c in range(COL_SUPP_START, COL_SUPP_END + 1)}
    import re as _re  # noqa: PLC0415
    for u in updates:
        col = _re.match(r"[A-Z]+", u["range"]).group(0)
        assert col in allowed, f"AC-AG 以外への書込を検出: {u['range']} (禁止)"
    CH = 60
    for i in range(0, len(updates), CH):
        ws.batch_update(updates[i:i + CH], value_input_option="USER_ENTERED")
    _log(f"書込完了: {len(updates)} セル")
    return 0


if __name__ == "__main__":
    sys.exit(main())
