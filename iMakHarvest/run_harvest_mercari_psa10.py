"""run_harvest_mercari_psa10 - メルカリ検索から PSA10 新規出品候補を収集 (cert 確定付き).

2026-08-17 新設 (user 依頼「ポーターのように PSA10 も」)。
ポーター (run_harvest_mercari_search.py) と 収集〜セラーフィルタまで同じ流れで、
**カード特定の段だけが違う**:

  ポーター: タイトルが「タンカーか」だけ見れば済む
  PSA10   : 「どのカードか」 を確証をもって決める必要がある (出品正確性原則)
            → スラブ写真から cert を読み (psa_slab_vision)、 PSA 公式で引いて
              ラベル項目が一致した物だけ通す (psa_cert.verify)

出品くん (iMakTCG) の入口が cert 番号なので、 確定した cert を渡せば下流はそのまま繋がる。

★2段構成にしてある理由: PSA 照合は psacard.com の レート制限が厳しく (2026-08-17 実測で
数発で 429、 復帰まで分単位)、 ここだけ時間がかかる。 収集結果を先に JSON へ落とし、
照合は `--verify-from-json` で何度でも再開できる (snkrdunk の --write-from-json と同方針)。
429 で確認できなかった cert は **通さない**。 未確認は「保留」であって「合格」ではない。

使い方:
  # ① 収集 + Vision 読取 (PSA 照合まで通しでやる)
  python run_harvest_mercari_psa10.py --dry-run --cap-per-keyword 20 --max-details 10
  # ② 照合だけ再開 (429 で落ちた分を後から埋める)
  python run_harvest_mercari_psa10.py --verify-from-json debug/mercari_psa10_<ts>.json
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

from scrapers import mercari_item_detail  # noqa: E402
from scrapers import mercari_search as MSch  # noqa: E402
from scrapers import mercari_seller as MS  # noqa: E402
from scrapers import psa_cert  # noqa: E402
from scrapers import psa_slab_vision  # noqa: E402

# iMakTCG が扱う 4 ゲーム (= ストアカテゴリがある物) に絞る。
# 「PSA10」 表記ゆれ (PSA10 / PSA 10) は メルカリ検索側が吸収するため片方で足りる。
DEFAULT_KEYWORDS = [
    "PSA10 ワンピースカード",
    "PSA10 ドラゴンボール カード",
    "PSA10 ガンダム カード",
    "PSA10 ポケモンカード",
]
DUMP_DIR = ROOT / "debug"


def _log(m: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


# ---------------------------------------------------------------------------
# ① 収集: メルカリ検索 → 詳細 → セラーフィルタ → Vision でラベル読取
# ---------------------------------------------------------------------------
def collect(args) -> dict:
    keywords = args.keywords or DEFAULT_KEYWORDS
    headless = args.headless and not args.manual  # manual は非 headless 必須
    _log(f"収集開始: keywords={len(keywords)} 価格={args.price_min}-{args.price_max} "
         f"評価数>={args.min_rating} mode={'手動フリマアシスト' if args.manual else '自動scroll'}")

    driver = MS.create_anonymous_driver(headless=headless)
    # vision_error は 「写真が読めない (= 正常な reject)」 とは別枠。 混ぜると API 障害を
    # 「不鮮明が多かった」 と読み違える (2026-08-17 に残高切れで実際に起きた)
    cands, rej = [], {"sold": 0, "seller_rating": 0, "no_identity": 0,
                      "fetch_fail": 0, "no_image": 0, "cert_unreadable": 0,
                      "vision_error": 0}
    vision_errors: list[str] = []
    try:
        collected = MSch.collect_multi_keyword_urls(
            keywords, driver, price_min=args.price_min, price_max=args.price_max,
            cap_per_keyword=args.cap_per_keyword, manual=args.manual,
            progress_callback=lambda n, m: _log(f"  収集 {m}"),
        )
        urls = collected["urls"]
        _log(f"収集: {len(urls)} URL (dedup後) / by_keyword={collected['by_keyword']}")
        if args.max_details:
            urls = urls[:args.max_details]
            _log(f"詳細フェッチ上限 {args.max_details} 件に制限")

        for i, url in enumerate(urls, 1):
            detail = mercari_item_detail.fetch_detail(driver, url)
            if not detail:
                rej["fetch_fail"] += 1
                continue
            if not detail.get("in_stock"):
                rej["sold"] += 1
                continue

            q = MSch.extract_seller_quality(driver)  # 直前に開いた商品ページから
            if not MSch.passes_seller_filter(
                q, min_rating_count=args.min_rating,
                require_identity=not args.no_identity,
            ):
                key = ("seller_rating" if (q.get("rating_count") or 0) < args.min_rating
                       else "no_identity")
                rej[key] += 1
                continue

            images = [u for u in (detail.get("image_urls") or []) if u.startswith("http")]
            if not images:
                rej["no_image"] += 1
                continue

            vision = psa_slab_vision.read_slab(images)
            if vision.get("error"):
                # こちらの障害 (残高切れ / rate limit 等)。 出品しない点は同じだが、
                # 黙って「不鮮明」に混ぜず 障害として最後に報告する
                rej["vision_error"] += 1
                vision_errors.append(vision["error"])
                continue
            # 通信なしで落とせる分はここで落とす (公式照会は 1 cert 1 回に抑えたいため)
            gate = psa_cert.local_gate(vision, detail.get("title") or "")
            if not gate["ok"]:
                key = gate["reason"].split(":")[0]
                rej[key] = rej.get(key, 0) + 1
                continue

            cands.append({
                "url": url,
                "title": detail.get("title"),
                "price_jpy": detail.get("price_jpy"),
                "condition": detail.get("condition"),
                "description": detail.get("description"),
                "image_urls": images,
                "seller_rating_count": q.get("rating_count"),
                "seller_star": q.get("star"),
                "identity_verified": q.get("identity_verified"),
                "vision": vision,
            })
            if i % 5 == 0 or i == len(urls):
                _log(f"  詳細 {i}/{len(urls)} (cert読取={len(cands)} rej={rej})")
            time.sleep(1.0)
    finally:
        try:
            driver.quit()
        except Exception:
            pass

    _log(f"収集完了: cert読取={len(cands)} / reject={rej}")
    if vision_errors:
        uniq = sorted(set(vision_errors))
        _log(f"⚠️ 要対応: Vision が {rej['vision_error']} 件で失敗 (= 判定できていない)。 "
             f"原因: {uniq[:3]}")
    return {"candidates": cands, "collect_reject": rej,
            "vision_errors": sorted(set(vision_errors)),
            "by_keyword": collected["by_keyword"]}


# ---------------------------------------------------------------------------
# ② 照合: PSA 公式で cert を引いて カードを確定 (レート制限あり・再開可)
# ---------------------------------------------------------------------------
def verify_all(cands: list[dict], interval: float, min_signals: int) -> dict:
    """未照合の候補だけ PSA 照合する (照合済は skip = 再開時に無駄打ちしない)."""
    todo = [c for c in cands if not (c.get("psa") or {}).get("ok")]
    _log(f"PSA 照合: 対象 {len(todo)}/{len(cands)} 件 (間隔 {interval}s)")
    stats = {"verified": 0, "cert_not_found": 0, "psa_unreachable": 0,
             "grade_not_psa10": 0, "label_mismatch": 0, "cert_unreadable": 0}
    for i, c in enumerate(todo, 1):
        res = psa_cert.verify(c["vision"], min_signals=min_signals)
        c["psa"] = res
        key = res["reason"].split(":")[0]
        stats[key] = stats.get(key, 0) + 1
        if res["ok"]:
            stats["verified"] += 1
            info = res["info"]
            _log(f"  [{i}/{len(todo)}] OK cert={res['cert']} "
                 f"{info.get('year')} {info.get('subject')} #{info.get('card_number')} "
                 f"({len(res['match']['signals'])}系統一致)")
        else:
            _log(f"  [{i}/{len(todo)}] NG cert={res['cert']} reason={res['reason']}")
        if i < len(todo):
            time.sleep(interval)
    return stats


def _dump(payload: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _log(f"[FILE] {path}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--price-min", type=int, default=3000)
    ap.add_argument("--price-max", type=int, default=100000)
    ap.add_argument("--min-rating", type=int, default=100, help="セラー評価数の下限")
    ap.add_argument("--no-identity", action="store_true", help="本人確認済 要件を外す")
    ap.add_argument("--cap-per-keyword", type=int, default=100)
    ap.add_argument("--max-details", type=int, default=0, help="詳細フェッチ上限 (0=無制限)")
    ap.add_argument("--keywords", nargs="*", default=None)
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--manual", action="store_true",
                    help="フリマアシスト手動click で volume 突破 (非headless必須)")
    ap.add_argument("--psa-interval", type=float, default=300.0,
                    help="PSA 照合の間隔秒 (429 回避。 2026-08-17 実測で数発/分は即 429)")
    ap.add_argument("--min-signals", type=int, default=2,
                    help="ラベル一致に要求する系統数 (既定2 = 1桁誤読を落とす)")
    ap.add_argument("--verify-from-json", default=None,
                    help="収集をやり直さず、 JSON の未照合分だけ PSA 照合し直す")
    ap.add_argument("--skip-verify", action="store_true",
                    help="収集と Vision 読取だけ行い PSA 照合はしない (後で再開)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    if args.verify_from_json:
        path = Path(args.verify_from_json)
        payload = json.loads(path.read_text(encoding="utf-8"))
        stats = verify_all(payload["candidates"], args.psa_interval, args.min_signals)
        payload["verify_stats"] = stats
        _dump(payload, path)
    else:
        payload = collect(args)
        path = DUMP_DIR / f"mercari_psa10_{datetime.now():%Y%m%dT%H%M%S}.json"
        _dump(payload, path)  # 照合前に必ず保存 (429 で落ちても収集をやり直さない)
        if args.skip_verify:
            _log("--skip-verify → PSA 照合は未実施。 --verify-from-json で再開できます")
            return 0
        stats = verify_all(payload["candidates"], args.psa_interval, args.min_signals)
        payload["verify_stats"] = stats
        _dump(payload, path)

    kept = [c for c in payload["candidates"] if (c.get("psa") or {}).get("ok")]
    _log(f"確定 (出品候補): {len(kept)} 件 / 照合内訳={payload['verify_stats']}")
    for c in kept:
        info = c["psa"]["info"]
        _log(f"  cert={c['psa']['cert']} ¥{c.get('price_jpy')} "
             f"{info.get('subject')} #{info.get('card_number')} {c['url']}")

    if args.dry_run:
        _log("dry-run → 書込なし")
    return 0


if __name__ == "__main__":
    sys.exit(main())
