"""run_harvest_mercari_chara - キャラ軸のトレジャーハント (HQ 依頼
`2026-09-21_chara_keywords_draft`).

`run_harvest_mercari_treasure.py` (カード番号軸 / demand_market.csv) とほぼ同じ作りだが
差分は3つ:
  ① 検索語 = HQ の `chara_market.csv` (テラピーク実売をキャラに束ねた一覧) の 和名のみ
  ② カードごとの上限仕入れ値は無い (会社の上限 ¥70,000 だけが効く = 上限判定列は書かない)
  ③ 書込先 = 中間スプシの **別タブ** `mercari_psa10_chara`
     (treasure と混ぜない。 上限判定列が無いなど列構成の意味が違うため)

一覧が空 (= HQ 側がまだ作っていない) なら **何もしない**。
週1回想定 (HQ 回答 2026-09-21)。

使い方:
  python run_harvest_mercari_chara.py --dry-run   # 確認
  python run_harvest_mercari_chara.py             # 本番
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from scrapers import chara_keywords  # noqa: E402
from scrapers import mercari_seller as MS  # noqa: E402
import run_harvest_mercari_psa10 as psa10  # noqa: E402
import run_marker  # noqa: E402

MARKER_PATH = ROOT / "debug" / "chara_running.flag"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

CHARA_TAB = "mercari_psa10_chara"
# ★2026-10-07 HQ依頼 🥕「拾った物は捨てない」: 候補外の理由 (treasureと同じ考え方)
COL_REASON = 38


def _log(m: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def _get_or_create_chara_ws(sh):
    import gspread  # noqa: PLC0415
    from sheet_writer_mercari_seller import _col_to_letter, _create_from_template, _ensure_header  # noqa: PLC0415

    try:
        ws = sh.worksheet(CHARA_TAB)
        _ensure_header(ws, sh)
    except gspread.WorksheetNotFound:
        ws = _create_from_template(sh, CHARA_TAB)
    header = ws.row_values(1)
    if len(header) < COL_REASON or header[COL_REASON - 1] != "候補外の理由":
        ws.update(range_name=f"{_col_to_letter(COL_REASON)}1",
                  values=[["候補外の理由"]], value_input_option="USER_ENTERED")
    return ws


def append_chara_items(items: list[dict], known_keys: set | None = None) -> dict:
    """`mercari_psa10_chara` タブへ append (item_id dedup)."""
    from sheet_writer_amazon import _build_row  # noqa: PLC0415
    from sheet_writer_mercari_search import dedupe_key, load_keys_all_tabs  # noqa: PLC0415
    from sheet_writer_mercari_seller import _col_to_letter, open_seller_staging_sheet  # noqa: PLC0415

    if not items:
        return {"tab": CHARA_TAB, "appended": 0, "skipped_existing": 0, "input": 0}

    sh = open_seller_staging_sheet()
    ws = _get_or_create_chara_ws(sh)
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
        while len(row) < COL_REASON - 1:
            row.append("")
        row.append(it.get("drop_reason") or "")
        new_rows.append(row)

    if not new_rows:
        return {"tab": CHARA_TAB, "appended": 0, "skipped_existing": skipped, "input": len(items)}

    header_len = COL_REASON
    last_row = len(ws.get_all_values())
    next_row = last_row + 1
    end_col_letter = _col_to_letter(header_len)
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
    return {"tab": CHARA_TAB, "appended": len(new_rows), "skipped_existing": skipped,
            "input": len(items)}


def _dropped_items(dropped: dict) -> list[dict]:
    """🥕「拾った物は捨てない」: collect(collect_dropped=True) が積んだ候補外の分を
    理由付きでスプシに書けるitem形に組み立てる (treasureと同じ考え方)。"""
    items = []
    for info in dropped.values():
        items.append({
            "url": info.get("url"), "title": info.get("title"), "condition": info.get("condition"),
            "price_jpy": info.get("price_jpy"), "image_urls": info.get("image_urls"),
            "description": info.get("description"), "cert": "",
            "fill_high_columns": False, "category": "TCG",
            "drop_reason": info.get("reason") or "",
        })
    return items


def _build_chara_args(keywords: list[str], ap_args, cost_cfg) -> argparse.Namespace:
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
        strict_gates=True,
        cost_cfg=cost_cfg,
        card_limits={},  # カード個別上限は無い。会社上限(cost_cfg)だけが効く
        monthly_cap_usd=getattr(ap_args, "monthly_cap_usd", 0),
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
                    help="落ちた走行の debug/mercari_chara_*.json を渡すと、"
                         " 収集済の検索語・処理済の商品を飛ばして続きから走る")
    # ★2026-10-07 HQ依頼 🥕「拾った物は捨てない」(treasureと同じ): 前回dumpの
    # collected_urls を対象に、鑑定番号を読まず候補外の理由だけ残す
    ap.add_argument("--add-dropped-from-json", default=None,
                    help="前回dumpの collected_urls を対象に、候補外の理由をシートに足す"
                         " (新規検索なし・鑑定番号読み取りなし)")
    # ★2026-10-17 HQ依頼 (B-20261017-007・treasureと同じ): 写真読みは月 約$45まで (合算)
    ap.add_argument("--monthly-cap-usd", type=float, default=45.0,
                    help="写真読み(課金)の月の上限ドル。 届いたら今回はそこで読むのを止める (0=無制限)")
    args = ap.parse_args(argv)

    from scrapers._chrome_util import kill_chrome_for_profile, kill_orphan_chromedriver
    kill_chrome_for_profile(MS.CHROME_PROFILE_DIR_ANON)
    kill_orphan_chromedriver()
    try:
        return _run(args)
    finally:
        kill_chrome_for_profile(MS.CHROME_PROFILE_DIR_ANON)
        kill_orphan_chromedriver()


def _run(args) -> int:
    # 仕入上限(会社全体の¥70,000)は HQ が共有領域に置く写しを読むだけ。 読めなければ
    # 全件素通しになる (fail-OPEN) ので、 走る前に止める。
    import run_harvest_mercari_psa10 as _p  # noqa: PLC0415
    try:
        cost_cfg = _p.load_cost_sanity()
    except Exception as e:  # noqa: BLE001
        _log(f"❌ 停止: 仕入上限の表を読めない ({_p.COST_SANITY_PATH}): {type(e).__name__}: {e}")
        return 2
    _log(f"仕入上限: ¥{cost_cfg['max_jpy']:,.0f} (共有領域の写しから / カード個別上限は無し)")
    rows = chara_keywords.load_rows()
    if not rows:
        _log(f"一覧が空 ({chara_keywords.CSV_PATH}) → 何もしない")
        return 0

    keywords = chara_keywords.build_keywords(rows)
    _log(f"キャラハント: 一覧 {len(rows)} 件 / 検索語 {len(keywords)} 語")

    resume = None
    if args.resume_from_json:
        dump_path = Path(args.resume_from_json)
        resume = json.loads(dump_path.read_text(encoding="utf-8"))
    else:
        # ★2026-10-17 HQ依頼 (B-20261017-007④・treasureと同じ): PCが落ちたら人の手を
        # 借りずに次回の起動で続きから入る。
        stale = run_marker.check_stale(MARKER_PATH)
        stale_dump = stale.get("dump_path") if stale else None
        if stale_dump and Path(stale_dump).exists():
            dump_path = Path(stale_dump)
            try:
                resume = json.loads(dump_path.read_text(encoding="utf-8"))
            except Exception as e:  # noqa: BLE001 - 読めなければ諦めて最初から
                _log(f"⚠️ 続きから再開しようとしたが控えを読めず ({type(e).__name__}) → 最初から")
                resume = None
        if resume is not None:
            done_n = len(resume.get("by_keyword") or {})
            _log(f"続きから再開: {done_n}/{len(keywords)}語目から "
                 f"(前回クラッシュ等で途中で止まった分・{dump_path})")
        else:
            dump_path = psa10.DUMP_DIR / f"mercari_chara_{datetime.now():%Y%m%dT%H%M%S}.json"
    _log(f"途中保存先: {dump_path}")
    # ★手動長時間収集は自動再開しない(HQ/ADV確定だったが B-20261017-007④ で自動化に変更)。
    # 開始時に印を残し、正常終了でだけ消す。
    run_marker.mark_started(MARKER_PATH, dump_path)
    chara_args = _build_chara_args(keywords, args, cost_cfg)

    # ★走行中にスプシへも書く (落ちた時に成果が0件になるのを防ぐ)。
    written: set = set()
    known: set = set()
    try:
        from sheet_writer_mercari_search import load_keys_all_tabs  # noqa: PLC0415
        from sheet_writer_mercari_seller import open_seller_staging_sheet  # noqa: PLC0415
        known = load_keys_all_tabs(open_seller_staging_sheet())
    except Exception as e:  # noqa: BLE001 - 読めなくても収集は続ける
        _log(f"⚠️ 既存キーを読めず (途中書込は自タブ dedupe のみ): {type(e).__name__}")

    # ★2026-10-18 HQ依頼 (B-20261017-007追記②・treasureと共有): 前回までに写真を読んで
    # 対象外と確定した URL は、 今回は写真の前に外す
    from scrapers import vision_reject_cache  # noqa: PLC0415
    pre_vision_excluded = vision_reject_cache.load_url_set()
    _log(f"写真読み済の控え (対象外確定): {len(pre_vision_excluded)} 件 → 今回は読む前に外す")

    def _flush(new_cands, new_unreadable):
        if args.dry_run or (not new_cands and not new_unreadable):
            return 0, 0
        items = psa10.build_sheet_items(new_cands, new_unreadable)
        try:
            res = append_chara_items(items, known_keys=known)
        except Exception as e:  # noqa: BLE001
            _log(f"  ⚠️ スプシ書込に失敗 ({type(e).__name__}) → 後でまとめて書く")
            return 0, 0
        written.update(i["url"] for i in items)
        _log(f"  [SHEET] 途中書込: {res}")
        return len(new_cands), len(new_unreadable)

    urls_override = None
    collect_dropped = False
    if args.add_dropped_from_json:
        src = json.loads(Path(args.add_dropped_from_json).read_text(encoding="utf-8"))
        urls_override = list(src.get("collected_urls") or [])
        chara_args.skip_vision = True
        collect_dropped = True
        _log(f"候補外の理由だけ残す: {len(urls_override)} URL (元 {args.add_dropped_from_json}・"
             f"新規検索なし・鑑定番号読み取りなし)")

    # ★2026-10-07 HQ依頼 (treasureと同じ): 詳細取得をAPI版にして、オークション形式の
    # ページでも「取得失敗」と誤判定しないようにする
    from scrapers.mercari_search_api import ApiSearchClient, fetch_detail_api  # noqa: PLC0415
    api_client = ApiSearchClient()

    def _detail_fn(u):
        try:
            return fetch_detail_api(api_client, u)
        except Exception as e:  # noqa: BLE001 - API側の不調はChromeにフォールバック
            _log(f"  ⚠️ 詳細(API版)失敗 ({type(e).__name__}) → この1件はChromeで読む")
            return None

    try:
        payload = psa10.collect(chara_args, dump_path=dump_path, resume=resume, on_flush=_flush,
                                urls_override=urls_override, detail_fn=_detail_fn,
                                collect_dropped=collect_dropped, skip_urls=known,
                                pre_vision_excluded=pre_vision_excluded)
    finally:
        api_client.close()

    new_post_vision = payload.get("post_vision_rejected") or {}
    added_n = vision_reject_cache.merge_and_save(new_post_vision)
    _log(f"写真を読んだ後に外した控えへ追加: {added_n} 件 (累計 {len(pre_vision_excluded) + added_n} 件)")

    kept = payload["candidates"]
    unreadable = payload.get("unreadable") or []
    _log(f"候補 (事前ゲート通過): {len(kept)} 件 / 番号読めず {len(unreadable)} 件")

    if args.dry_run:
        _log("dry-run → 書込なし")
        run_marker.mark_finished(MARKER_PATH)
        return 0

    rest_k = [c for c in kept if c.get("url") not in written]
    rest_u = [c for c in unreadable if c.get("url") not in written]
    dropped_res = None
    if collect_dropped:
        dropped = payload.get("dropped") or {}
        dropped_res = append_chara_items(_dropped_items(dropped), known_keys=known)
        _log(f"🥕 候補外の理由を足した: {dropped_res}")
    if not rest_k and not rest_u:
        if dropped_res is None:
            _log("[SHEET] 走行中に全部書込済")
        run_marker.mark_finished(MARKER_PATH)
        return 0

    res = append_chara_items(psa10.build_sheet_items(rest_k, rest_u), known_keys=known)
    _log(f"[SHEET] {res}")
    run_marker.mark_finished(MARKER_PATH)
    return 0


if __name__ == "__main__":
    sys.exit(main())
