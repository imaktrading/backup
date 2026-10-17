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
import run_marker  # noqa: E402

MARKER_PATH = ROOT / "debug" / "treasure_running.flag"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

TREASURE_TAB = "mercari_psa10_treasure"
COL_JUDGMENT = 36  # AJ: 上限判定 (上限内/超過/空欄) - このタブ専用の末尾追加列
# ★2026-10-07 HQ依頼 (promo_60_add_dropped) 🥕「拾った物は捨てない」: 候補外の理由
COL_REASON = 39
# ★2026-10-15 HQ依頼 (治療ハントの量の調整): シートに入れる候補が約N件で打ち切る時、
# 回しきれなかった語を次回の先頭に積んでおく控え
LEFTOVER_PATH = Path("C:/dev/iMak_data/harvest/treasure_leftover_keywords.json")


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
    header = ws.row_values(1)
    if len(header) < COL_REASON or header[COL_REASON - 1] != "候補外の理由":
        ws.update(range_name=f"{_col_to_letter(COL_REASON)}1",
                  values=[["候補外の理由"]], value_input_option="USER_ENTERED")
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
        row.append(it.get("cost_judgment") or "")  # 36: 上限判定
        row.append("")  # 37: 巡回ERR (他処理が使う列、ここでは書かない)
        row.append("")  # 38: トレジャー (同上)
        row.append(it.get("drop_reason") or "")  # 39: 候補外の理由
        new_rows.append(row)

    if not new_rows:
        return {"tab": TREASURE_TAB, "appended": 0,
                "skipped_existing": skipped, "input": len(items)}

    last_row = len(ws.get_all_values())
    next_row = last_row + 1
    end_col_letter = _col_to_letter(COL_REASON)
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


def _build_treasure_args(keywords: list[str], ap_args, cost_cfg, card_limits) -> argparse.Namespace:
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
        strict_gates=True,
        cost_cfg=cost_cfg,
        card_limits=card_limits,
        max_vision=getattr(ap_args, "max_vision", 0),
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
                    help="落ちた走行の debug/mercari_treasure_*.json を渡すと、"
                         " 収集済の検索語・処理済の商品を飛ばして続きから走る")
    # ★2026-10-07 HQ依頼 (2026-10-07_treasure_mew_two_words): 912語フル走行でなく
    # 指定した語だけに絞る時に使う (パイプ区切り。 例: "PSA10 ミュウ 343/S-P|PSA10 ミュウ ババ抜き")
    ap.add_argument("--keywords", default=None,
                    help="demand_market.csv の全語ではなく、この語だけで回す (パイプ区切り)")
    # 鑑定番号の読み取り(従量課金API)に上限を付ける。 0=無制限 (既定)
    ap.add_argument("--max-vision", type=int, default=0)
    # ★2026-10-07 HQ依頼 (2026-10-07_treasure_promo_60): demand_market.csv でなく
    # 別の一覧(抜粋ファイル)から検索語・上限仕入れ値を作る時に使う
    ap.add_argument("--csv-path", default=None,
                    help="demand_market.csv の代わりに読む一覧 (列は同じ形式)")
    # ★2026-10-07 HQ依頼 (2026-10-07_treasure_promo_60_failed_retry): 前回の
    # debug/mercari_treasure_*.json の failed_urls だけ、検索せずに詳細取得をやり直す
    ap.add_argument("--retry-failed-from-json", default=None,
                    help="前回dumpの failed_urls だけ拾い直す (新規検索なし)")
    # ★2026-10-07 HQ依頼 (2026-10-07_treasure_promo_60_add_dropped) 🥕「拾った物は捨てない」:
    # 前回dumpの collected_urls 全部を対象に、候補にしなかった理由を残して書く (vision なし)
    ap.add_argument("--add-dropped-from-json", default=None,
                    help="前回dumpの collected_urls を対象に、候補外の理由をシートに足す"
                         " (新規検索なし・鑑定番号読み取りなし)")
    # ★2026-10-15 HQ依頼: シートに入れる候補が約N件になったら、残りの語は回さず次回に回す
    ap.add_argument("--max-candidates", type=int, default=0,
                    help="シートに書き込んだ候補がこの件数に届いたら打ち切る (0=無制限)")
    # ★2026-10-17 HQ依頼 (B-20261017-007): 写真読みは月 約$45まで (トレハン・キャラハン合算)。
    # 0=無制限 (従来互換)
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


def _treasure_items(kept: list[dict], unreadable: list[dict],
                    limits: dict[str, int]) -> list[dict]:
    """スプシ書込用 item に 上限判定を足す (psa10 の item 組立を流用)."""
    items = psa10.build_sheet_items(kept, unreadable)
    for it in items:
        it["cost_judgment"] = treasure_keywords.judge_cost(
            it.get("title"), it.get("price_jpy"), limits)
    return items


def _dropped_items(dropped: dict) -> list[dict]:
    """🥕「拾った物は捨てない」(2026-10-07 HQ依頼): collect(collect_dropped=True) が
    積んだ候補外の分を、理由付きでスプシに書けるitem形に組み立てる。 鑑定番号は無い
    (読んでいないので cert 空欄・候補扱いにはしない)。"""
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


def _run(args) -> int:
    # 仕入上限は HQ が共有領域に置く写しを読むだけ。 読めなければ 7時間走って
    # 全件素通しになる (fail-OPEN) ので、 走る前に止める。
    import run_harvest_mercari_psa10 as _p  # noqa: PLC0415
    try:
        cost_cfg = _p.load_cost_sanity()
    except Exception as e:  # noqa: BLE001
        _log(f"❌ 停止: 仕入上限の表を読めない ({_p.COST_SANITY_PATH}): {type(e).__name__}: {e}")
        return 2
    _log(f"仕入上限: ¥{cost_cfg['max_jpy']:,.0f} (共有領域の写しから)")
    csv_path = Path(args.csv_path) if args.csv_path else None
    rows = treasure_keywords.load_rows(csv_path)
    if not rows:
        _log(f"一覧が空 ({csv_path or treasure_keywords.CSV_PATH}) → 何もしない")
        return 0

    limits = treasure_keywords.build_cost_limits(rows)
    leftover_prev: list[str] = []
    if args.keywords:
        keywords = [k for k in args.keywords.split("|") if k.strip()]
        _log(f"検索語を指定分だけに絞った: {keywords}")
    else:
        # ★2026-10-15 HQ依頼: 「売れた数」の多い順に回す
        def _sold(r):
            try:
                return int(float(r.get("売れた数") or 0))
            except ValueError:
                return 0
        rows_sorted = sorted(rows, key=_sold, reverse=True)
        keywords = treasure_keywords.build_keywords(rows_sorted)
        # 前回打ち切りで残した語があれば、今回の先頭に積む (無ければ無視)
        try:
            prev = json.loads(LEFTOVER_PATH.read_text(encoding="utf-8"))
            if prev.get("csv_path") == str(csv_path or treasure_keywords.CSV_PATH):
                leftover_prev = [k for k in (prev.get("keywords") or []) if k in keywords]
        except Exception:  # noqa: BLE001 - 控えが無い/壊れていても今回は普通に回す
            leftover_prev = []
        if leftover_prev:
            rest = [k for k in keywords if k not in leftover_prev]
            keywords = leftover_prev + rest
            _log(f"前回残した語を先頭に積んだ: {len(leftover_prev)} 語")
    _log(f"トレジャーハント: 一覧 {len(rows)} 件 / 検索語 {len(keywords)} 語")

    resume = None
    if args.resume_from_json:
        dump_path = Path(args.resume_from_json)
        resume = json.loads(dump_path.read_text(encoding="utf-8"))
    else:
        # ★2026-10-17 HQ依頼 (B-20261017-007④): PCが落ちたら、人の手を借りずに
        # 次回の起動で続きから入る (従来は手で --resume-from-json を撃つ運用だった)。
        # 印 (treasure_running.flag) が残っている = 前回クラッシュ等で途中で止まった分。
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
            dump_path = psa10.DUMP_DIR / f"mercari_treasure_{datetime.now():%Y%m%dT%H%M%S}.json"
    _log(f"途中保存先: {dump_path}")
    # ★開始時に印を残し、 正常終了(mark_finished)でだけ消す (自動再開しない運用だったが
    # B-20261017-007④ で「次回の起動で続きから」に変更。 印が残っている=前回クラッシュ等で
    # 途中で止まった、 を次の起動が above で検出して自動で resume= に読み込む)。
    run_marker.mark_started(MARKER_PATH, dump_path)
    treasure_args = _build_treasure_args(keywords, args, cost_cfg, limits)

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

    def _should_pause():
        return bool(args.max_candidates) and len(written) >= args.max_candidates

    urls_override = None
    collect_dropped = False
    if args.retry_failed_from_json:
        src = json.loads(Path(args.retry_failed_from_json).read_text(encoding="utf-8"))
        urls_override = list(src.get("failed_urls") or [])
        _log(f"失敗分だけ拾い直す: {len(urls_override)} URL (元 {args.retry_failed_from_json}・新規検索なし)")
    if args.add_dropped_from_json:
        src = json.loads(Path(args.add_dropped_from_json).read_text(encoding="utf-8"))
        urls_override = list(src.get("collected_urls") or [])
        treasure_args.skip_vision = True
        collect_dropped = True
        _log(f"候補外の理由だけ残す: {len(urls_override)} URL (元 {args.add_dropped_from_json}・"
             f"新規検索なし・鑑定番号読み取りなし)")

    # ★2026-10-07 HQ依頼 (promo_60_failed_retry): 詳細取得がChrome頼みだとオークション形式
    # ページのセレクタが合わず「取得失敗」になる (出品は生きている・status=on_sale)。
    # kagoya_treasure_offload.py と同じAPI版detail_fnに切替、形式を問わず読めるようにする。
    from scrapers.mercari_search_api import ApiSearchClient, fetch_detail_api  # noqa: PLC0415
    api_client = ApiSearchClient()

    def _detail_fn(u):
        try:
            return fetch_detail_api(api_client, u)
        except Exception as e:  # noqa: BLE001 - API側の不調はChromeにフォールバック
            _log(f"  ⚠️ 詳細(API版)失敗 ({type(e).__name__}) → この1件はChromeで読む")
            return None

    try:
        payload = psa10.collect(treasure_args, dump_path=dump_path, resume=resume,
                                on_flush=_flush, urls_override=urls_override, detail_fn=_detail_fn,
                                collect_dropped=collect_dropped, skip_urls=known,
                                should_pause=_should_pause if args.max_candidates else None)
    finally:
        api_client.close()

    kept = payload["candidates"]
    unreadable = payload.get("unreadable") or []
    _log(f"候補 (事前ゲート通過): {len(kept)} 件 / 番号読めず {len(unreadable)} 件")

    # ★2026-10-15 HQ依頼: 打ち切りで回せなかった語を控えて次回の先頭に積む。
    # 「回した語」は detail処理(写真読みの前の段階含む)が実際に届いた分で判定する
    # (シート書込の有無やdry-runとは無関係)
    if not args.keywords and not args.retry_failed_from_json and not args.add_dropped_from_json:
        by_kw = payload.get("by_keyword") or {}
        processed_n = len(payload.get("processed_urls") or [])
        cum = 0
        ran_kw: list[str] = []
        left_kw: list[str] = []
        for kw in keywords:
            n = by_kw.get(kw, 0)
            cum += n
            if cum <= processed_n:
                ran_kw.append(kw)
            else:
                left_kw.append(kw)
        # ★2026-10-16 HQ依頼 (B-20261015-022): 検索中に Chrome が切れて飛ばした語は
        # 「落ちた語は残した語に入れて次回の先頭へ」。 ran_kw から除いて先頭に積む
        search_crashed = payload.get("search_crashed_keywords") or []
        ran_kw = [k for k in ran_kw if k not in search_crashed]
        left_kw = list(dict.fromkeys(search_crashed + left_kw))
        try:
            LEFTOVER_PATH.parent.mkdir(parents=True, exist_ok=True)
            LEFTOVER_PATH.write_text(json.dumps(
                {"csv_path": str(csv_path or treasure_keywords.CSV_PATH), "keywords": left_kw},
                ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception as e:  # noqa: BLE001 - 控えを書けなくても走行結果は残す
            _log(f"⚠️ 残した語の控えを書けず: {type(e).__name__}")
        cap_hit = bool(payload.get("truncated"))
        _log(f"📘 打ち切り: {'候補の上限で区切った' if cap_hit else '打ち切りなし'} / "
             f"回した語 {len(ran_kw)} / 残した語 {len(left_kw)} "
             f"(うち検索で落ちた語 {len(search_crashed)})")

    if args.dry_run:
        _log("dry-run → 書込なし")
        run_marker.mark_finished(MARKER_PATH)
        return 0

    rest_k = [c for c in kept if c.get("url") not in written]
    rest_u = [c for c in unreadable if c.get("url") not in written]
    dropped_res = None
    if collect_dropped:
        dropped = payload.get("dropped") or {}
        dropped_res = append_treasure_items(_dropped_items(dropped), known_keys=known)
        _log(f"🥕 候補外の理由を足した: {dropped_res}")
    if not rest_k and not rest_u:
        if dropped_res is None:
            _log("[SHEET] 走行中に全部書込済")
        run_marker.mark_finished(MARKER_PATH)
        return 0

    res = append_treasure_items(_treasure_items(rest_k, rest_u, limits),
                               known_keys=known)
    _log(f"[SHEET] {res}")
    run_marker.mark_finished(MARKER_PATH)
    return 0


if __name__ == "__main__":
    sys.exit(main())
