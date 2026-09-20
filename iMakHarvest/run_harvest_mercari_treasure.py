"""run_harvest_mercari_treasure - 市場で売れている(が うちが出していない)カードだけを
夜間に メルカリ検索から集める (HQ 依頼 `2026-09-18_treasure_hunt_harvest`).

**既存の `run_harvest_mercari_psa10.py` は触らない。** cert 抽出パイプライン (収集→詳細
→セラーフィルタ→Vision→ローカルゲート) はそのまま import して使い、差分は 2 つだけ:

  ① 検索語 = HQ の `demand_market.csv` (eBay 実売台帳ベース) の 和名+番号
  ② 書込先 = 中間スプシの **単一タブ** `mercari_psa10_treasure`
              (ゲーム別に分けない。 末尾列に 上限判定 [上限内/超過] を足す)

一覧が空 (= HQ 側がまだ作っていない) なら **何もしない** (HQ 回答 2026-09-18)。

使い方:
  python run_harvest_mercari_treasure.py --dry-run   # 確認
  python run_harvest_mercari_treasure.py             # 本番 (夜間 cron から叩く想定)
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from scrapers import mercari_seller as MS  # noqa: E402
from scrapers import treasure_keywords  # noqa: E402
import run_harvest_mercari_psa10 as psa10  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

TREASURE_TAB = "mercari_psa10_treasure"
COL_JUDGMENT = 36  # AJ: 上限判定 (上限内/超過/空欄) - このタブ専用の末尾追加列


def _log(m: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def _get_or_create_treasure_ws(sh):
    import gspread  # noqa: PLC0415
    from sheet_writer_mercari_seller import (  # noqa: PLC0415
        _col_to_letter,
        _create_from_template,
        _ensure_header,
    )

    try:
        ws = sh.worksheet(TREASURE_TAB)
        _ensure_header(ws, sh)
    except gspread.WorksheetNotFound:
        ws = _create_from_template(sh, TREASURE_TAB)
    header = ws.row_values(1)
    if len(header) < COL_JUDGMENT or header[COL_JUDGMENT - 1] != "上限判定":
        ws.update(range_name=f"{_col_to_letter(COL_JUDGMENT)}1",
                  values=[["上限判定"]], value_input_option="USER_ENTERED")
    return ws


def append_treasure_items(items: list[dict], known_keys: set | None = None) -> dict:
    """`mercari_psa10_treasure` タブへ append (item_id dedup + 末尾に上限判定列)."""
    from sheet_writer_amazon import _build_row  # noqa: PLC0415
    from sheet_writer_mercari_search import dedupe_key, load_keys_all_tabs  # noqa: PLC0415
    from sheet_writer_mercari_seller import (  # noqa: PLC0415
        _col_to_letter,
        open_seller_staging_sheet,
    )

    if not items:
        return {"tab": TREASURE_TAB, "appended": 0, "skipped_existing": 0, "input": 0}

    sh = open_seller_staging_sheet()
    ws = _get_or_create_treasure_ws(sh)
    existing = set(known_keys) if known_keys is not None else load_keys_all_tabs(sh)

    new_rows: list[list[str]] = []
    seen_in_batch: set[str] = set()
    skipped = 0
    for it in items:
        url = (it.get("url") or "").strip()
        key = dedupe_key(url)
        if not key or key in existing or key in seen_in_batch:
            skipped += 1
            continue
        seen_in_batch.add(key)
        row = _build_row(it)
        row.append(it.get("cost_judgment") or "")
        new_rows.append(row)

    if not new_rows:
        return {"tab": TREASURE_TAB, "appended": 0,
                "skipped_existing": skipped, "input": len(items)}

    last_row = len(ws.get_all_values())
    next_row = last_row + 1
    end_col_letter = _col_to_letter(COL_JUDGMENT)
    end_row = next_row + len(new_rows) - 1
    try:
        short = end_row - int(getattr(ws, "row_count", 0) or 0)
        if short > 0:
            ws.add_rows(short + 200)
    except Exception:  # noqa: BLE001 - 足せなくても書込は試す
        pass
    ws.update(range_name=f"A{next_row}:{end_col_letter}{end_row}",
              values=new_rows, value_input_option="USER_ENTERED")
    if known_keys is not None:
        known_keys.update(seen_in_batch)
    return {"tab": TREASURE_TAB, "appended": len(new_rows),
            "skipped_existing": skipped, "input": len(items)}


def _build_treasure_args(keywords: list[str], ap_args) -> argparse.Namespace:
    """collect() が読む属性だけを持たせた args (= psa10 の既定値を踏襲)."""
    return argparse.Namespace(
        keywords=keywords,
        games=None,
        from_demand=False,
        demand_only=False,
        demand_limit=0,
        headless=ap_args.headless,
        manual=ap_args.manual,
        price_min=ap_args.price_min,
        price_max=ap_args.price_max,
        min_rating=ap_args.min_rating,
        no_identity=False,
        cap_per_keyword=ap_args.cap_per_keyword,
        keyword_interval=ap_args.keyword_interval,
        max_details=ap_args.max_details,
        no_dedupe=False,
        save_every=10,
        sheet_every=30,
        max_consecutive_errors=3,
    )


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--price-min", type=int, default=3000)
    ap.add_argument("--price-max", type=int, default=70000)
    ap.add_argument("--min-rating", type=int, default=100)
    ap.add_argument("--cap-per-keyword", type=int, default=100)
    ap.add_argument("--max-details", type=int, default=0)
    ap.add_argument("--keyword-interval", type=float, default=8.0)
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--manual", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--resume-from-json", default=None,
                    help="落ちた走行の debug/mercari_treasure_*.json を渡すと、"
                         " 収集済の検索語・処理済の商品を飛ばして続きから走る")
    args = ap.parse_args(argv)

    from scrapers._chrome_util import kill_chrome_for_profile, kill_orphan_chromedriver
    kill_chrome_for_profile(MS.CHROME_PROFILE_DIR_ANON)
    kill_orphan_chromedriver()
    try:
        return _run(args)
    finally:
        kill_chrome_for_profile(MS.CHROME_PROFILE_DIR_ANON)
        kill_orphan_chromedriver()


def _treasure_items(kept: list[dict], unreadable: list[dict],
                    limits: dict[str, int]) -> list[dict]:
    """スプシ書込用 item に 上限判定を足す (psa10 の item 組立を流用)."""
    items = psa10.build_sheet_items(kept, unreadable)
    for it in items:
        it["cost_judgment"] = treasure_keywords.judge_cost(
            it.get("title"), it.get("price_jpy"), limits)
    return items


def _run(args) -> int:
    rows = treasure_keywords.load_rows()
    if not rows:
        _log(f"一覧が空 ({treasure_keywords.CSV_PATH}) → 何もしない")
        return 0

    keywords = treasure_keywords.build_keywords(rows)
    limits = treasure_keywords.build_cost_limits(rows)
    _log(f"トレジャーハント: 一覧 {len(rows)} 件 / 検索語 {len(keywords)} 語")

    resume = None
    if args.resume_from_json:
        dump_path = Path(args.resume_from_json)
        resume = json.loads(dump_path.read_text(encoding="utf-8"))
    else:
        dump_path = psa10.DUMP_DIR / f"mercari_treasure_{datetime.now():%Y%m%dT%H%M%S}.json"
    _log(f"途中保存先: {dump_path}")
    treasure_args = _build_treasure_args(keywords, args)

    # ★走行中にスプシへも書く。 最後にまとめて書くと、 落ちた時にその走行の成果が
    # 1 行も残らない (2026-09-13 に UT 収集で 140 件を失った型)。
    written: set = set()
    known: set = set()
    try:
        from sheet_writer_mercari_search import load_keys_all_tabs  # noqa: PLC0415
        from sheet_writer_mercari_seller import (  # noqa: PLC0415
            open_seller_staging_sheet,
        )
        known = load_keys_all_tabs(open_seller_staging_sheet())
    except Exception as e:  # noqa: BLE001 - 読めなくても収集は続ける
        _log(f"⚠️ 既存キーを読めず (途中書込は自タブ dedupe のみ): {type(e).__name__}")

    def _flush(new_cands, new_unreadable):
        """走行中の途中書込。 スプシ側のエラーで走行を殺さない
        (書けなかった分は written に入らないので最終書込で拾い直される)。
        """
        if args.dry_run or (not new_cands and not new_unreadable):
            return 0, 0
        items = _treasure_items(new_cands, new_unreadable, limits)
        try:
            res = append_treasure_items(items, known_keys=known)
        except Exception as e:  # noqa: BLE001
            _log(f"  ⚠️ スプシ書込に失敗 ({type(e).__name__}) → 後でまとめて書く")
            return 0, 0
        written.update(i["url"] for i in items)
        _log(f"  [SHEET] 途中書込: {res}")
        return len(new_cands), len(new_unreadable)

    payload = psa10.collect(treasure_args, dump_path=dump_path, resume=resume,
                            on_flush=_flush)

    kept = payload["candidates"]
    unreadable = payload.get("unreadable") or []
    _log(f"候補 (事前ゲート通過): {len(kept)} 件 / 番号読めず {len(unreadable)} 件")

    if args.dry_run:
        _log("dry-run → 書込なし")
        return 0

    rest_k = [c for c in kept if c.get("url") not in written]
    rest_u = [c for c in unreadable if c.get("url") not in written]
    if not rest_k and not rest_u:
        _log("[SHEET] 走行中に全部書込済")
        return 0

    res = append_treasure_items(_treasure_items(rest_k, rest_u, limits),
                               known_keys=known)
    _log(f"[SHEET] {res}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
