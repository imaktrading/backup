"""run_harvest_mercari_uniqlo - メルカリから **ユニクロ UT / GU のコラボT** を集める.

2026-08-22 新設 (user 依頼「メルカリでユニクロのTシャツを抽出したい」)。
user 確定: **UT + GU のコラボT / 新品・未使用のみ**。

`run_harvest_mercari_search.py` (ポーター用) と同じ資産を使うが、 判定が別物なので
runner を分けた (あちらは `is_tanker` / `is_target_bag` に固定されている)。

落とす順:
  ① 検索URLで絞る … 販売中 / 送料込み / 価格帯 / **新品・未使用 (item_condition_id=1)**
  ② タイトルで落とす … ユニクロ or GU の T かつ **コラボ物**。まとめ売り・キッズ・難ありは捨てる
  ③ 商品ページで落とす … 売切れ / 状態が「新品、未使用」でない / セラー評価数・本人確認

使い方:
  python run_harvest_mercari_uniqlo.py --dry-run --max-details 10     # 下見
  python run_harvest_mercari_uniqlo.py                                 # 本番
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

import uniqlo_tee  # noqa: E402
from scrapers import mercari_item_detail  # noqa: E402
from scrapers import mercari_search as MSch  # noqa: E402
from scrapers import mercari_seller as MS  # noqa: E402

# UT/GU は「ブランド語 + IP名」で探すのが素直 (無地に埋もれない)。
# 語は増やしてよい。 減らすと取りこぼす。
DEFAULT_KEYWORDS = [
    "ユニクロ UT ワンピース Tシャツ",
    "ユニクロ UT ポケモン Tシャツ",
    "ユニクロ UT 鬼滅の刃 Tシャツ",
    "ユニクロ UT 呪術廻戦 Tシャツ",
    "ユニクロ UT ドラゴンボール Tシャツ",
    "ユニクロ UT スヌーピー Tシャツ",
    "ユニクロ UT ジブリ Tシャツ",
    "ユニクロ UT ディズニー Tシャツ",
    "GU コラボ Tシャツ アニメ",
    "ユニクロ UT コラボ Tシャツ 新品",
]
DUMP_DIR = ROOT / "debug"


def _log(m: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def to_sheet_item(k: dict) -> dict:
    """keep した item -> スプシ書込用 (純関数). X=見つけた語 / Y=タグの番号."""
    return {"url": k["url"], "title": k.get("title"), "condition": k.get("condition"),
            "price_jpy": k.get("price_jpy"), "image_urls": k.get("image_urls"),
            "description": k.get("description"), "size": k.get("size"),
            "color": k.get("color"),
            "found_by_term": k.get("found_by_term"),     # X
            "tag_number": k.get("tag_number")}           # Y


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    # ★UT の価格帯は 500〜12,000円 (2026-09-13 user 確定)。 既定にしておく = 付け忘れても効く
    ap.add_argument("--price-min", type=int, default=500)
    ap.add_argument("--price-max", type=int, default=12000)
    ap.add_argument("--min-rating", type=int, default=100, help="セラー評価数の下限")
    ap.add_argument("--no-identity", action="store_true", help="本人確認済 要件を外す")
    ap.add_argument("--cap-per-keyword", type=int, default=60)
    ap.add_argument("--max-details", type=int, default=0, help="詳細フェッチ上限 (0=無制限)")
    ap.add_argument("--keywords", nargs="*", default=None)
    ap.add_argument("--allow-used", action="store_true",
                    help="新品・未使用以外も通す (既定は 新品・未使用のみ)")
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--manual", action="store_true",
                    help="フリマアシスト『もっと見る』を手動 click して件数を伸ばす")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--label", default="uniqlo_ut", help="中間スプシ tab (= mercari_<label>)")
    ap.add_argument("--from-catalog", type=int, default=0, metavar="N",
                    help="カタログの『公式で買えない UT』のコラボ名から N 語を作って検索する")
    ap.add_argument("--anime-only", action="store_true",
                    help="アニメ・漫画のコラボだけにする (2026-09-13 user 確定)")
    ap.add_argument("--max-keep", type=int, default=0,
                    help="この件数を集めたら止める (POC 用。0=止めない)")
    ap.add_argument("--no-tag-read", action="store_true",
                    help="タグの商品番号を Vision で読まない")
    args = ap.parse_args(argv)

    # ★カタログ起点: 公式売り切れ UT のコラボ名で引く (「公式で買えない新品未使用」を狙う)
    term_of: dict[str, str] = {}          # 検索語 -> カタログのコラボ名 (目視の材料)
    if args.from_catalog:
        import uniqlo_catalog_terms as T  # noqa: PLC0415
        from scrapers.rakuten_search import is_excluded_category  # noqa: PLC0415
        terms = T.build_terms(args.from_catalog, excluded=is_excluded_category,
                              only_anime=args.anime_only)
        keywords = [T.query_for(t["term"]) for t in terms]
        term_of = {T.query_for(t["term"]): t["term"] for t in terms}
        _log(f"カタログの売り切れ UT から {len(keywords)} 語")
    else:
        keywords = args.keywords or DEFAULT_KEYWORDS
    headless = args.headless and not args.manual
    conds = None if args.allow_used else [MSch.CONDITION_NEW]
    _log(f"開始: 語={len(keywords)} 価格={args.price_min}-{args.price_max} "
         f"状態={'新品・未使用のみ' if conds else '指定なし'} 評価数>={args.min_rating}")

    from scrapers._chrome_util import kill_chrome_for_profile
    killed = kill_chrome_for_profile(MS.CHROME_PROFILE_DIR_ANON)
    if killed:
        _log(f"前回の残留 chrome を {killed} 個 片付けました")

    # ★落ちても途中まで残す (2026-09-13 実害: 140件 keep した後に chromedriver が
    #   ReadTimeout で落ち、 書込が最後だけだったため **140件が丸ごと消えた**)。
    #   user 指示「途中で保存するようにしてね / 途中で落ちてやり直しはやめろよ」を
    #   楽天側にしか入れていなかった。 ここにも同じ守りを入れる:
    #     1) 5件ごとにスプシへ書く (書けなければ持ち越し、 最後まで駄目ならファイルに退避)
    #     2) 1件ごとに JSON を書く
    #     3) ドライバの例外は1件の失敗として数え、 連続3件で再起動 (最大3回)
    #     4) 既にスプシにある出品は 詳細を開かない (回し直しても Vision を二重に払わない)
    DUMP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%dT%H%M%S")
    dump = DUMP_DIR / f"mercari_uniqlo_{ts}.json"
    known: set = set()
    if not args.dry_run:
        try:
            from sheet_writer_mercari_seller import open_seller_staging_sheet  # noqa: PLC0415
            from sheet_writer_mercari_search import load_keys_all_tabs  # noqa: PLC0415
            known = load_keys_all_tabs(open_seller_staging_sheet())
            _log(f"中間スプシに既にあるメルカリ出品: {len(known)} 件 (詳細を開かない)")
        except Exception as e:  # noqa: BLE001
            _log(f"⚠️ 既存キーを読めず: {type(e).__name__} (重複は書込時に弾く)")
    from sheet_writer_mercari_search import dedupe_key  # noqa: PLC0415

    def _new_driver():
        kill_chrome_for_profile(MS.CHROME_PROFILE_DIR_ANON)
        return MS.create_anonymous_driver(headless=headless)

    driver = MS.create_anonymous_driver(headless=headless)
    kept: list[dict] = []
    pending: list[dict] = []
    written = 0
    restarts = 0
    rej = {"sold": 0, "not_uniqlo_tee": 0, "not_collab": 0, "not_new": 0,
           "seller_rating": 0, "no_identity": 0, "fetch_fail": 0, "already_in_sheet": 0}
    collected = {"urls": [], "by_keyword": {}}

    def _flush(rows: list[dict]) -> bool:
        nonlocal written
        if args.dry_run or not rows:
            return True
        from sheet_writer_mercari_search import append_mercari_search_items  # noqa: PLC0415
        try:
            res = append_mercari_search_items([to_sheet_item(k) for k in rows],
                                              label=args.label, known_keys=known)
            written += res.get("appended", 0)
            _log(f"  [SHEET] {res}")
            return True
        except Exception as e:  # noqa: BLE001 - 書込失敗で走行を殺さない
            _log(f"  ⚠️ スプシ書込に失敗 ({type(e).__name__}) → 持ち越し ({len(rows)}件)")
            return False

    def _dump():
        dump.write_text(json.dumps({"kept": kept, "reject": rej,
                                    "by_keyword": collected["by_keyword"]},
                                   ensure_ascii=False, indent=2), encoding="utf-8")

    try:
        # 語ごとに集める = 各URLを **どの語で見つけたか** を覚えておける (X列の材料)
        found_by: dict[str, str] = {}
        urls, by_kw = [], {}
        for idx, kw in enumerate(keywords):
            if idx:
                time.sleep(8.0)
            try:
                r = MSch.collect_search_listing_urls(
                    kw, driver, price_min=args.price_min, price_max=args.price_max,
                    cap=args.cap_per_keyword, manual=args.manual,
                    item_condition_ids=conds,
                    progress_callback=lambda n, m: _log(f"  収集 {m}"))
            except Exception as e:  # noqa: BLE001 - 1語の失敗で全体を止めない
                _log(f"  ⚠️ '{kw}' 検索失敗 ({type(e).__name__}) → ドライバを作り直して次の語へ")
                try:
                    driver.quit()
                except Exception:  # noqa: BLE001
                    pass
                driver = _new_driver()
                by_kw[kw] = 0
                continue
            added = 0
            for u in r["urls"]:
                if u in found_by:
                    continue
                found_by[u] = term_of.get(kw, "")
                urls.append(u)
                added += 1
            by_kw[kw] = added
            _log(f"  '{kw}': 新規 {added}")
        collected = {"urls": urls, "by_keyword": by_kw}
        _log(f"収集: {len(urls)} URL / by_keyword={collected['by_keyword']}")
        if args.max_details:
            urls = urls[:args.max_details]
            _log(f"詳細 {args.max_details} 件に制限")

        consecutive_fail = 0
        for url in urls:
            if dedupe_key(url) in known:
                rej["already_in_sheet"] += 1
                continue
            try:
                detail = mercari_item_detail.fetch_detail(driver, url)
            except Exception as e:  # noqa: BLE001 - ドライバが固まった等
                _log(f"  ⚠️ 詳細取得で例外 ({type(e).__name__}) {url}")
                detail = None
            if not detail:
                rej["fetch_fail"] += 1
                consecutive_fail += 1
                if consecutive_fail >= 3:
                    if pending and _flush(pending):
                        pending = []
                    if restarts >= 3:
                        _log("  ⚠️ 再起動しても直らないので中断します (ここまでは保存済)")
                        break
                    restarts += 1
                    _log(f"  ⚠️ 連続 {consecutive_fail} 件失敗 → ドライバを再起動 ({restarts}回目)")
                    try:
                        driver.quit()
                    except Exception:  # noqa: BLE001
                        pass
                    driver = _new_driver()
                    consecutive_fail = 0
                continue
            consecutive_fail = 0
            if not detail.get("in_stock"):
                rej["sold"] += 1
                continue
            title = detail.get("title") or ""
            if not uniqlo_tee.is_uniqlo_tee(title):
                rej["not_uniqlo_tee"] += 1
                continue
            # ★カタログの語で見つけた行は、 その語がタイトルに入っていればコラボ物とみなす
            #   (佐藤可士和展 / POP MART / TOKYO 等は 手書きのコラボ語リストに無く、
            #    POC 初回で12件を「コラボでない」で落としていた)
            found_term = found_by.get(url, "")
            if not uniqlo_tee.is_collab(title) and not (found_term and found_term in title):
                # 無地・エアリズムは海外で価格が付かない (user 確定 2026-08-22)
                rej["not_collab"] += 1
                continue
            if not args.allow_used and not uniqlo_tee.is_new_condition(
                    detail.get("condition") or ""):
                rej["not_new"] += 1
                continue
            try:
                q = MSch.extract_seller_quality(driver)
            except Exception as e:  # noqa: BLE001
                _log(f"  ⚠️ セラー情報で例外 ({type(e).__name__}) {url}")
                rej["fetch_fail"] += 1
                continue
            if not MSch.passes_seller_filter(
                    q, min_rating_count=args.min_rating,
                    require_identity=not args.no_identity):
                key = ("seller_rating" if (q.get("rating_count") or 0) < args.min_rating
                       else "no_identity")
                rej[key] += 1
                continue
            item = dict(detail)
            item["url"] = url
            item["seller_rating_count"] = q.get("rating_count")
            # 目視の材料 (KEY ではない。 AI列には書かない)
            item["found_by_term"] = found_by.get(url, "")
            if not args.no_tag_read:
                from scrapers.ut_tag_vision import read_tag_number  # noqa: PLC0415
                tag = read_tag_number(detail.get("image_urls") or [])
                item["tag_number"] = tag["number"]
                if tag["error"]:
                    rej["tag_read_error"] = rej.get("tag_read_error", 0) + 1
            kept.append(item)
            pending.append(item)
            _dump()
            _log(f"  keep {len(kept)}件目 ¥{detail.get('price_jpy')} "
                 f"[{item.get('found_by_term') or '-'}] tag={item.get('tag_number') or '-'} "
                 f"{title[:32]}")
            if len(pending) >= 5 and _flush(pending):
                pending = []
            if args.max_keep and len(kept) >= args.max_keep:
                _log(f"{args.max_keep}件に達したので止めます")
                break
            time.sleep(1.0)
    finally:
        try:
            driver.quit()
        except Exception:  # noqa: BLE001
            pass
        _dump()
        if pending and not _flush(pending):
            left = DUMP_DIR / f"mercari_uniqlo_unwritten_{ts}.json"
            left.write_text(json.dumps({"unwritten": pending}, ensure_ascii=False, indent=2),
                            encoding="utf-8")
            _log(f"  ⚠️ 書けなかった {len(pending)}件を {left.name} に退避 (要再投入)")

    status = "正常" if rej["fetch_fail"] == 0 else f"⚠️要対応 (取得失敗 {rej['fetch_fail']}件)"
    _log(f"完了: 収集{len(collected['urls'])} → keep={len(kept)} / スプシに書いた {written} "
         f"/ 落とした内訳={rej} / {status}")
    _log(f"[FILE] {dump}")
    if args.dry_run:
        _log("dry-run → 書込なし")
    return 0


if __name__ == "__main__":
    sys.exit(main())
