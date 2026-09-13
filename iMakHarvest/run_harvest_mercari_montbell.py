"""run_harvest_mercari_montbell - メルカリから **モンベルのジャケット系** を集める.

2026-09-05 新設 (user 依頼「モンベルのジャケット系も抽出したい」)。 user 確定:
  - **中古と新品の両方**を拾う。 状態は E列で見分けられるようにする
  - **型番 (7桁) の読み取りはしない**。 画像を見る判断は出品側の目視に任せる

`run_harvest_mercari_uniqlo.py` と同じ骨格。 判定だけ `montbell_jacket` に差し替え。

使い方:
  python run_harvest_mercari_montbell.py --dry-run --max-details 12   # 下見
  python run_harvest_mercari_montbell.py                              # 本番
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

import montbell_jacket  # noqa: E402
from scrapers import mercari_item_detail  # noqa: E402
from scrapers import mercari_search as MSch  # noqa: E402
from scrapers import mercari_seller as MS  # noqa: E402

# シリーズ名で引く (「モンベル ジャケット」だけだと寝袋・小物に埋もれる)。
# 語は増やしてよい。 減らすと取りこぼす。
DEFAULT_KEYWORDS = [
    "モンベル ストームクルーザー ジャケット",
    "モンベル ウインドブラスト パーカ",
    "モンベル サンダーパス ジャケット",
    "モンベル ライトシェル ジャケット",
    "モンベル バーサライト ジャケット",
    "モンベル レイントレッカー ジャケット",
    "モンベル インナーダウン ジャケット",
    "モンベル クリマエア ジャケット",
    "モンベル フリース ジャケット",
    "montbell ジャケット メンズ",
]
DUMP_DIR = ROOT / "debug"


def _log(m: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def to_sheet_item(k: dict) -> dict:
    """keep した item -> スプシ書込用 (純関数). E列 = 新品 / 中古."""
    return {"url": k["url"], "title": k.get("title"),
            "condition": k["condition_label"],
            "price_jpy": k.get("price_jpy"), "image_urls": k.get("image_urls"),
            "description": k.get("description"), "size": k.get("size"),
            "color": k.get("color")}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--price-min", type=int, default=4000)
    ap.add_argument("--price-max", type=int, default=30000)
    ap.add_argument("--min-rating", type=int, default=100, help="セラー評価数の下限")
    ap.add_argument("--no-identity", action="store_true")
    ap.add_argument("--cap-per-keyword", type=int, default=40)
    ap.add_argument("--max-details", type=int, default=0)
    ap.add_argument("--keywords", nargs="*", default=None)
    ap.add_argument("--new-only", action="store_true",
                    help="新品・未使用だけにする (既定は 中古も拾う)")
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--manual", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--label", default="montbell_jacket")
    args = ap.parse_args(argv)

    keywords = args.keywords or DEFAULT_KEYWORDS
    headless = args.headless and not args.manual
    conds = [MSch.CONDITION_NEW] if args.new_only else None
    _log(f"開始: 語={len(keywords)} 価格={args.price_min}-{args.price_max} "
         f"状態={'新品のみ' if conds else '中古+新品'} 評価数>={args.min_rating}")

    from scrapers._chrome_util import kill_chrome_for_profile
    killed = kill_chrome_for_profile(MS.CHROME_PROFILE_DIR_ANON)
    if killed:
        _log(f"前回の残留 chrome を {killed} 個 片付けました")

    # ★途中で保存する (2026-09-13 user「なんでまめな保存をしないの？」)。
    #   最後だけ書く作りだと、 ドライバが1回落ちるだけで それまでの収集が全部消える
    #   (同日 メルカリUT で 140件消失)。 5件ごとに書き、 1件ごとに JSON を残す。
    from incremental_writer import PendingWriter  # noqa: PLC0415
    DUMP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%dT%H%M%S")
    dump = DUMP_DIR / f"mercari_montbell_{ts}.json"

    def _write(rows):
        from sheet_writer_mercari_search import append_mercari_search_items  # noqa: PLC0415
        _log(f"  [SHEET] {append_mercari_search_items([to_sheet_item(k) for k in rows], label=args.label)}")

    writer = PendingWriter(write_fn=_write, every=5, dump_path=dump, log=_log,
                           enabled=not args.dry_run)
    driver = MS.create_anonymous_driver(headless=headless)
    kept: list[dict] = []
    rej = {"sold": 0, "not_montbell_jacket": 0, "seller_rating": 0,
           "no_identity": 0, "fetch_fail": 0}
    collected = {"urls": [], "by_keyword": {}}
    try:
        collected = MSch.collect_multi_keyword_urls(
            keywords, driver, price_min=args.price_min, price_max=args.price_max,
            cap_per_keyword=args.cap_per_keyword, manual=args.manual,
            item_condition_ids=conds, sleep_between_sec=8.0,
            progress_callback=lambda n, m: _log(f"  収集 {m}"),
        )
        urls = collected["urls"]
        _log(f"収集: {len(urls)} URL / by_keyword={collected['by_keyword']}")
        if args.max_details:
            urls = urls[:args.max_details]

        for url in urls:
            try:
                detail = mercari_item_detail.fetch_detail(driver, url)
            except Exception as e:  # noqa: BLE001 - ドライバが固まった等。 1件の失敗として数える
                _log(f"  ⚠️ 詳細取得で例外 ({type(e).__name__}) {url}")
                detail = None
            if not detail:
                rej["fetch_fail"] += 1
                continue
            if not detail.get("in_stock"):
                rej["sold"] += 1
                continue
            title = detail.get("title") or ""
            if not montbell_jacket.is_montbell_jacket(title):
                rej["not_montbell_jacket"] += 1
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
            # ★E列は **新品 / 中古** に正規化して入れる (user 確定: 列で見分けられるように)
            item["condition_label"] = montbell_jacket.condition_label(
                detail.get("condition") or "")
            item["seller_rating_count"] = q.get("rating_count")
            kept.append(item)
            writer.add(item)
            _log(f"  keep {len(kept)}件目 ¥{detail.get('price_jpy')} "
                 f"[{item['condition_label']}] {title[:40]}")
            time.sleep(1.0)
    finally:
        try:
            driver.quit()
        except Exception:  # noqa: BLE001
            pass
        writer.close()      # 残りを書く。 書けなければ _unwritten.json に退避

    news = sum(1 for k in kept if k["condition_label"] == "新品")
    _log(f"完了: 収集{len(collected['urls'])} → keep={len(kept)} "
         f"(新品{news} / 中古{len(kept) - news}) / 落とした内訳={rej}")
    status = "正常" if rej["fetch_fail"] == 0 else f"⚠️要対応 (取得失敗 {rej['fetch_fail']}件)"
    _log(f"スプシに書いた {writer.written} 件 / {status} / [FILE] {dump}")
    if args.dry_run:
        _log("dry-run → 書込なし")
    return 0


if __name__ == "__main__":
    sys.exit(main())
