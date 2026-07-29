"""run_gshock_merge - G-shock 商品管理シート(LOW=1jF9vggb)にヨドバシを型番マージする恒久配線.

設計思想 (HQ `..._multisource_merge_feasibility(_hq_confirm)` + user 2026-07-26):
  - **毎cycle ヨドバシ抽出(yodobashi_gshock)全型番を LOW に型番突合**する。
  - **LOW と被る型番** → その全行の AC-AG 補URL にヨドバシURLを**冪等追記**(先回り冗長化。
    Amazon が後で 3rd化しても既に補URLが載っている=延命が即効く)。
  - **LOW 未収載の型番** → **new_candidates(新規出品候補)として別出し**(JSON)。
    ※新規出品の作成(タイトル/画像/Item Specifics/eBay)は listing project 責務。Harvest は候補提示まで。
  - **D列(在庫状態)は touch しない**(= Inventory 責務。 誤復活防止)。

分界 (HQ 確定): Harvest=補URL(データ)冪等追記 + 新規候補別出し / Inventory=D復活・M-min(状態)。
冪等性 = gshock_merge.compute_merge (空枠のみ・満杯skip・既存/主URL重複skip)。
同一型番が LOW 複数行に在れば **該当全行**に追記(補URLはデータ、行毎に独立)。

使い方:
  python run_gshock_merge.py --dry-run          # 全ヨドバシ型番で書込計画+新規候補 (書込なし)
  python run_gshock_merge.py                     # AC-AG 実書込 + 新規候補 JSON 出力
  python run_gshock_merge.py --source <json>     # {model,url} list を明示指定 (既定=yodobashi_gshock タブ)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from gshock_merge import compute_merge  # noqa: E402
from harvest_stamp import check_previous_stamp, write_stamp  # noqa: E402
from scrapers.yodobashi_search_http import extract_model_from_title  # noqa: E402
from sheet_writer_amazon import (  # noqa: E402
    LISTINGS_GID,
    LOW_SHEET_ID,
    get_listings_worksheet,
    open_sheet_by_id,
)

COL_URL = 1        # A
COL_D = 4          # D 売切 (= 絶対 touch しない)
COL_FLG = 17       # Q FLG (= yodobashi_gshock に LOW未収載フラグを立てる列)
COL_KEY_SRC = 35   # AI 型番 (yodobashi_gshock/LOW 共通)
FLG_NEW = "新規"    # LOW 未収載 (= 新規出品候補) を表すフラグ値
COL_SUPP_START = 29  # AC
COL_SUPP_END = 33    # AG (補URL 1-5)
COL_KEY = 35       # AI 型番
NEW_CANDIDATES_JSON = Path(
    r"c:\dev\iMak_data\catalog\_amazon_jp_dumps\yodobashi_new_to_low.json")
STAMP_PATH = Path(r"c:\dev\iMak_data\harvest\gshock_merge_stamp.json")
STAMP_STALE_HOURS = 25  # cron cadence=1日1回 → 25h 超で warn (依頼書 §3)


def _log(m: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def _with_retry(fn, what: str, attempts: int = 5):
    """DNS flapping (getaddrinfo 断続失敗、 2026-07 環境) 耐性の backoff リトライ."""
    last = None
    for att in range(1, attempts + 1):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            last = e
            _log(f"  {what} retry {att}/{attempts} ({type(e).__name__}) → backoff")
            time.sleep(5 * att)
    raise last


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


def _open_yodobashi_tab():
    """yodobashi_gshock worksheet + 全行 vals を返す (DNS リトライ付)."""
    from sheet_writer_mercari_seller import open_seller_staging_sheet  # noqa: PLC0415
    ws = _with_retry(
        lambda: open_seller_staging_sheet().worksheet("yodobashi_gshock"),
        "yodobashi_gshock open")
    vals = _with_retry(ws.get_all_values, "yodobashi_gshock get_all_values")
    return ws, vals


def _source_from_yodobashi_vals(vals) -> list[dict]:
    out = []
    for r in vals[1:]:
        model = _cell(r, COL_KEY_SRC)
        url = _cell(r, COL_URL)
        if model and url:
            out.append({"model": model, "url": url})
    return out


def _flag_new_candidates(yws, yvals, new_models: set, dry_run: bool) -> int:
    """yodobashi_gshock の Q(FLG)列に LOW未収載フラグを冪等更新.

    LOW未収載型番の行 → Q="新規"、 LOW収載済(=補URL対象)の行 → Q="" (クリア)。
    現値と一致する行は書かない (冪等・最小書込)。 Returns: 書込セル数。
    """
    updates = []
    for i, r in enumerate(yvals[1:], start=2):
        model = _cell(r, COL_KEY_SRC).upper()
        if not model:
            continue
        desired = FLG_NEW if model in new_models else ""
        cur = _cell(r, COL_FLG)
        if cur == desired:
            continue
        updates.append({"range": f"{_col_letter(COL_FLG)}{i}", "values": [[desired]]})
    _log(f"FLG(Q列) 更新計画: {len(updates)} 行 (新規={FLG_NEW!r} / 収載済=クリア)")
    if dry_run or not updates:
        return len(updates)
    CH = 60
    for k in range(0, len(updates), CH):
        chunk = updates[k:k + CH]
        _with_retry(
            lambda c=chunk: yws.batch_update(c, value_input_option="USER_ENTERED"),
            f"FLG batch_update[{k}]")
    _log(f"FLG 書込完了: {len(updates)} セル")
    return len(updates)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--source", default=None,
                    help="{model,url} list の JSON (既定=yodobashi_gshock タブ全型番)")
    args = ap.parse_args(argv)

    # 前回スタンプの鮮度チェック (silent 死 検知、 fail-open で続行)
    check_previous_stamp(STAMP_PATH, STAMP_STALE_HOURS, label="gshock_merge")

    yws = yvals = None
    if args.source:
        src = json.loads(Path(args.source).read_text(encoding="utf-8"))
        src_name = Path(args.source).name
    else:
        yws, yvals = _open_yodobashi_tab()  # FLG 書込に再利用
        src = _source_from_yodobashi_vals(yvals)
        src_name = "yodobashi_gshock(tab)"
    # {model(大文字): url} (同型番複数URLは最初の1つ)
    model_url = {}
    for x in src:
        m = (x.get("model") or "").upper()
        u = (x.get("url") or "").strip()
        if m and u and m not in model_url:
            model_url[m] = u
    _log(f"投入型番: {len(model_url)} (source={src_name})")

    ws = _with_retry(
        lambda: get_listings_worksheet(open_sheet_by_id(LOW_SHEET_ID), LISTINGS_GID),
        "LOW open")
    vals = _with_retry(ws.get_all_values, "LOW get_all_values")
    _log(f"LOW 総行: {len(vals)}")

    # 行単位で existing_by_key を構築 (キー = 行番号、 同型番複数行を独立に扱う)
    existing_by_key: dict[str, dict] = {}
    row_meta: dict[str, dict] = {}          # rowkey -> {rownum, model, empty_cols[list]}
    new_items: list[dict] = []
    matched_models: set[str] = set()
    for i, row in enumerate(vals[1:], start=2):
        model = _row_model(row)
        if model not in model_url:
            continue
        matched_models.add(model)
        empty_cols = [c for c in range(COL_SUPP_START, COL_SUPP_END + 1)
                      if not _cell(row, c)]
        supp_urls = [_cell(row, c) for c in range(COL_SUPP_START, COL_SUPP_END + 1)
                     if _cell(row, c)]
        rk = str(i)
        existing_by_key[rk] = {"primary_url": _cell(row, COL_URL), "supp_urls": supp_urls}
        row_meta[rk] = {"rownum": i, "model": model, "empty_cols": empty_cols}
        new_items.append({"model": rk, "url": model_url[model], "source": "yodobashi"})

    # 新規候補 = 投入型番のうち LOW に 1 行も無いもの (= 純粋に LOW 追記すべき新規出品候補)
    new_candidate_models = sorted(set(model_url) - matched_models)
    _log(f"LOW 被り型番: {len(matched_models)} (該当行 {len(existing_by_key)}) / "
         f"LOW未収載(新規候補): {len(new_candidate_models)}")

    plan = compute_merge(existing_by_key, new_items)
    _log(f"補URL: 追記対象行={len(plan['supp_additions'])} "
         f"冪等skip(既存)={plan['skipped_dup']} 満杯skip={plan['skipped_full']}")

    # rowkey -> AC-AG セル書込 (空枠に順に)
    updates = []
    for rk, urls in plan["supp_additions"].items():
        meta = row_meta[rk]
        empty = meta["empty_cols"]
        for j, u in enumerate(urls):
            if j >= len(empty):
                break
            cell = f"{_col_letter(empty[j])}{meta['rownum']}"
            updates.append({"range": cell, "values": [[u]]})

    _log(f"補URL 書込計画: {len(updates)} セル (AC-AG のみ、 D列 不触)")

    # 新規候補を JSON 別出し (= listing project 用) + 中間スプシ yodobashi_gshock の
    # Q(FLG)列にフラグ (= user 指示、 シート上で新規出品対象が一目で分かる)。
    new_out = [{"model": m, "url": model_url[m]} for m in new_candidate_models]
    if not args.dry_run:
        NEW_CANDIDATES_JSON.write_text(
            json.dumps(new_out, ensure_ascii=False, indent=2), encoding="utf-8")
        _log(f"新規候補 {len(new_out)} 件 → {NEW_CANDIDATES_JSON.name} (LOW未書込・listing用)")
    else:
        _log(f"新規候補 {len(new_out)} 件 (dry-run: JSON未出力)。先頭: "
             f"{[m for m in new_candidate_models[:10]]}")

    # yodobashi_gshock の FLG(Q列) を冪等更新 (source=タブ の時のみ = 行位置が対応)
    if yws is not None and yvals is not None:
        _flag_new_candidates(yws, yvals, set(new_candidate_models), args.dry_run)
    elif args.source:
        _log("FLG更新skip (--source 指定時は yodobashi_gshock 行位置と対応しないため)")

    written = 0
    if args.dry_run:
        _log("dry-run: 補URL 書込なし")
        _log("[stamp] skip (--dry-run)")
        return 0
    if updates:
        # 安全弁: 書込先は AC-AG 列のみ (D=在庫状態 等を絶対に触らない)
        allowed = {_col_letter(c) for c in range(COL_SUPP_START, COL_SUPP_END + 1)}
        import re as _re  # noqa: PLC0415
        for u in updates:
            col = _re.match(r"[A-Z]+", u["range"]).group(0)
            assert col in allowed, f"AC-AG 以外への書込を検出: {u['range']} (禁止)"
        CH = 60
        for i in range(0, len(updates), CH):
            chunk = updates[i:i + CH]
            _with_retry(
                lambda c=chunk: ws.batch_update(c, value_input_option="USER_ENTERED"),
                f"batch_update[{i}]")
            written += len(chunk)
        _log(f"補URL 書込完了: {written} セル")
    else:
        _log("補URL 書込対象なし (全て冪等skip)")

    # 完走スタンプ書込 (dry_run 時は書かない = 本番未走を dry_run で潰さないため)
    stamp = write_stamp(STAMP_PATH, {
        "yodobashi_models": len(model_url),
        "matched_low_rows": len(existing_by_key),
        "matched_models": len(matched_models),
        "new_candidates": len(new_candidate_models),
        "supp_url_appended_cells": written,
        "dry_run": False,
    })
    _log(f"[stamp] wrote {STAMP_PATH.name} ok_at={stamp['ok_at']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
