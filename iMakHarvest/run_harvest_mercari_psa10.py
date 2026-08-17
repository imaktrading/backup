"""run_harvest_mercari_psa10 - メルカリ検索から PSA10 新規出品候補を収集 (cert 確定付き).

2026-08-17 新設 (user 依頼「ポーターのように PSA10 も」)。
ポーター (run_harvest_mercari_search.py) と 収集〜セラーフィルタまで同じ流れで、
**カード特定の段だけが違う**:

  ポーター: タイトルが「タンカーか」だけ見れば済む
  PSA10   : 「どのカードか」 を確証をもって決める必要がある (出品正確性原則)
            → スラブ写真から cert を読み (psa_slab_vision)、 PSA 公式で引いて
              ラベル項目が一致した物だけ通す (psa_cert.verify)

★出力先 = 中間スプシの `mercari_psa10` タブ (= ポーターの `mercari_porter` と同じ扱い)。
本番 (HIGH 商品管理シート) には直接入れない。 user 判断 (2026-08-17): まず中間で見る。
列は本番と同じ位置に入れてあるので、 移す時に組み替えは要らない:
  A 列 = メルカリ URL / I 列 = cert。
本番へ移すと、 出品くん (iMakTCG psa_to_csv) が
`I列(cert#)非空 AND B列(itemID)空 AND A列(URL)非空` の行を PSA 出品対象として拾う。

★PSA 公式照会は既定で **やらない** (2026-08-17 方針確定)。
psacard.com は Cloudflare で弾かれるが、 出品くん側に既に対策が入っている
(起動時に画面ありブラウザで 1 回手動突破 → 同 driver 使い回し + 1 件 15 秒間隔)。
同じ所を Harvest からも叩くと制限を食い合うだけなので、 **公式照会は出品くんに 1 本化**する。
Harvest 側は通信の要らない事前ゲート (psa_cert.local_gate) までを担当する。
先に確定させたい時だけ `--verify` を付ける (要 Cloudflare 突破、 1 件 5 分間隔)。

使い方:
  python run_harvest_mercari_psa10.py --keywords "PSA10 ワンピースカード" --dry-run  # 確認
  python run_harvest_mercari_psa10.py --keywords "PSA10 ワンピースカード"            # 本番
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
from scrapers import psa_search_terms  # noqa: E402
from scrapers import psa_slab_vision  # noqa: E402

# キーワードは psa_search_terms が弾コード単位で組む。
# 2026-08-17 実測: メルカリ検索は 1 語 15 件で頭打ち (価格・送料条件を外しても増えない) だが、
# **語を増やすとほぼ線形に積み上がる** (弾コード 10 語 → 148 件、 重複 2 件のみ)。
# ゲーム名だけの 4 語だと 60 件が上限になるので、 弾コードで刻む。
DUMP_DIR = ROOT / "debug"


# Windows の既定コンソールは cp932。 収集も書込も終わった後に ログ 1 行の
# UnicodeEncodeError で落ちると、 何件通ったのか分からなくなる (2026-08-17 に発生)。
# stdout を UTF-8 にして、 それでも駄目な文字は化けさせてでも処理を続ける。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001 - reconfigure 不可の環境でも処理は続ける
    pass


def _log(m: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


# ---------------------------------------------------------------------------
# ① 収集: メルカリ検索 → 詳細 → セラーフィルタ → Vision でラベル読取
# ---------------------------------------------------------------------------
def collect(args, dump_path=None, resume=None) -> dict:
    """収集 → 詳細 → Vision。

    ★途中で落ちても作業を捨てない (2026-08-17 の事故対策)。
    ドライバとの通信が 1 回タイムアウトしただけで走行全体が例外死し、 詳細 145 件
    (Vision 読取 111 回 = 課金済) が丸ごと消えた。 原因は 2 つ:
      ① 保存が全ループ終了後の 1 回だけだった
      ② 1 件の失敗が走行全体を殺していた
    → `--save-every` 件ごとに JSON へ保存し、 1 件の失敗はその 1 件だけ落とす。
      連続で失敗したらドライバを作り直し、 それでも駄目なら **そこまでを保存して
      「途中まで」と明示して**終わる (黙って正常終了しない)。
    """
    keywords = args.keywords or psa_search_terms.build_keywords(args.games)
    headless = args.headless and not args.manual  # manual は非 headless 必須
    _log(f"収集開始: keywords={len(keywords)} 価格={args.price_min}-{args.price_max} "
         f"評価数>={args.min_rating} mode={'手動フリマアシスト' if args.manual else '自動scroll'}")

    def _new_driver():
        return MS.create_anonymous_driver(headless=headless)

    driver = _new_driver()
    # vision_error は 「写真が読めない (= 正常な reject)」 とは別枠。 混ぜると API 障害を
    # 「不鮮明が多かった」 と読み違える (2026-08-17 に残高切れで実際に起きた)
    cands, rej = [], {"sold": 0, "seller_rating": 0, "no_identity": 0,
                      "fetch_fail": 0, "no_image": 0, "cert_unreadable": 0,
                      "vision_error": 0, "already_claimed_url": 0,
                      "already_claimed_cert": 0, "item_error": 0}
    vision_errors: list[str] = []
    # 鑑定番号が読めなかった分 (= I列空欄でスプシに入れて目視で拾う。 2026-08-18 user 指示)
    unreadable: list[dict] = []
    by_keyword: dict = {}

    # 再開: 前回の JSON にある URL は処理済として飛ばす (収集自体は速いのでやり直す)
    done_urls: set[str] = set()
    if resume:
        cands = list(resume.get("candidates") or [])
        unreadable = list(resume.get("unreadable") or [])
        for k, v in (resume.get("collect_reject") or {}).items():
            rej[k] = rej.get(k, 0) + v
        done_urls = set(resume.get("processed_urls") or [])
        _log(f"再開: 処理済 {len(done_urls)} URL / 既存候補 {len(cands)} 件")
    processed: list[str] = list(done_urls)
    state = {"truncated": False}

    def _save():
        """途中経過を JSON に落とす。 これが 1 回だけだったのが 2026-08-17 の事故。"""
        if not dump_path:
            return
        _dump({"candidates": cands, "unreadable": unreadable, "collect_reject": rej,
               "vision_errors": sorted(set(vision_errors)),
               "processed_urls": processed, "truncated": state["truncated"],
               "by_keyword": by_keyword}, dump_path, quiet=True)

    # 本番で既に押さえてある仕入元は拾い直さない (URL は詳細フェッチの前に落とすので
    # 1 件あたり 約10秒 と Vision 1 回分が丸ごと浮く)
    claimed = {"urls": set(), "certs": set()}
    if not args.no_dedupe:
        from sheet_writer import load_claimed_supply  # noqa: PLC0415
        claimed = load_claimed_supply()
        _log(f"既知の仕入元: URL {len(claimed['urls'])} 件 / cert {len(claimed['certs'])} 件")

    from sheet_writer import dedupe_key  # noqa: PLC0415
    try:
        collected = MSch.collect_multi_keyword_urls(
            keywords, driver, price_min=args.price_min, price_max=args.price_max,
            cap_per_keyword=args.cap_per_keyword, manual=args.manual,
            sleep_between_sec=args.keyword_interval,
            progress_callback=lambda n, m: _log(f"  収集 {m}"),
        )
        urls = collected["urls"]
        by_keyword = collected["by_keyword"]
        _log(f"収集: {len(urls)} URL (dedup後) / by_keyword={by_keyword}")
        if args.max_details:
            urls = urls[:args.max_details]
            _log(f"詳細フェッチ上限 {args.max_details} 件に制限")
        _save()  # 収集直後に保存 (詳細で落ちても URL 収集をやり直さない)

        consecutive_errors = 0
        for i, url in enumerate(urls, 1):
            if url in done_urls:
                continue
            if dedupe_key(url) in claimed["urls"]:
                rej["already_claimed_url"] += 1
                processed.append(url)
                continue
            try:
                kept = _process_one(url, driver, args, claimed, rej, vision_errors)
                consecutive_errors = 0
            except Exception as e:  # noqa: BLE001 - 1 件の失敗で走行全体を殺さない
                rej["item_error"] += 1
                consecutive_errors += 1
                _log(f"  ⚠️ {i}/{len(urls)} 取得エラー ({consecutive_errors}連続): "
                     f"{type(e).__name__}")
                _save()
                if consecutive_errors >= args.max_consecutive_errors:
                    # ドライバが死んでいる可能性が高い。 作り直して続行を試す
                    _log("  ドライバを作り直します")
                    try:
                        driver.quit()
                    except Exception:
                        pass
                    try:
                        driver = _new_driver()
                        consecutive_errors = 0
                    except Exception as e2:  # noqa: BLE001
                        state["truncated"] = True
                        _log(f"  ドライバ再生成も失敗 ({type(e2).__name__}) → ここで打ち切り")
                        break
                continue
            processed.append(url)
            if kept is not None:
                (cands if kept.get("cert_readable", True) else unreadable).append(kept)
            if len(processed) % args.save_every == 0:
                _save()
            if i % 5 == 0 or i == len(urls):
                _log(f"  詳細 {i}/{len(urls)} (cert読取={len(cands)} "
                     f"番号読めず={len(unreadable)} rej={rej})")
            time.sleep(1.0)
    finally:
        _save()  # 例外で抜けても保存する
        try:
            driver.quit()
        except Exception:
            pass

    _log(f"収集完了{'(途中まで)' if state['truncated'] else ''}: "
         f"cert読取={len(cands)} / 番号読めず={len(unreadable)} (I列空欄で投入) "
         f"/ reject={rej}")
    if vision_errors:
        uniq = sorted(set(vision_errors))
        _log(f"⚠️ 要対応: Vision が {rej['vision_error']} 件で失敗 (= 判定できていない)。 "
             f"原因: {uniq[:3]}")
    if state["truncated"]:
        _log("⚠️ 要対応: 途中で打ち切りました。 --resume-from-json で続きから再開できます")
    return {"candidates": cands, "unreadable": unreadable, "collect_reject": rej,
            "vision_errors": sorted(set(vision_errors)),
            "processed_urls": processed, "truncated": state["truncated"],
            "by_keyword": by_keyword}


def _process_one(url, driver, args, claimed, rej, vision_errors):
    """1 件を判定して 候補 dict を返す (対象外なら None)。 例外は呼出側で捕まえる."""
    detail = mercari_item_detail.fetch_detail(driver, url)
    if not detail:
        rej["fetch_fail"] += 1
        return None
    if not detail.get("in_stock"):
        rej["sold"] += 1
        return None

    q = MSch.extract_seller_quality(driver)  # 直前に開いた商品ページから
    if not MSch.passes_seller_filter(
        q, min_rating_count=args.min_rating,
        require_identity=not args.no_identity,
    ):
        key = ("seller_rating" if (q.get("rating_count") or 0) < args.min_rating
               else "no_identity")
        rej[key] += 1
        return None

    images = [u for u in (detail.get("image_urls") or []) if u.startswith("http")]
    if not images:
        rej["no_image"] += 1
        return None

    vision = psa_slab_vision.read_slab(images)
    if vision.get("error"):
        # こちらの障害 (残高切れ / rate limit 等)。 出品しない点は同じだが、
        # 黙って「不鮮明」に混ぜず 障害として最後に報告する
        rej["vision_error"] += 1
        vision_errors.append(vision["error"])
        return None
    # 通信なしで落とせる分はここで落とす (公式照会は 1 cert 1 回に抑えたいため)
    gate = psa_cert.local_gate(vision, detail.get("title") or "")
    if not gate["ok"]:
        key = gate["reason"].split(":")[0]
        rej[key] = rej.get(key, 0) + 1
        # ★user 指示 (2026-08-18): 鑑定番号が読めなかった分は捨てずに I列空欄で入れる
        # (目視で拾うため)。 grade が PSA10 でない等 「対象外と分かった」 物は従来通り捨てる。
        if key == "cert_unreadable":
            return _build_candidate(url, detail, q, images, vision,
                                    cert_readable=False)
        return None
    # 同じ現物が別 URL で再出品されている場合は URL 突合では捕まらない。
    # cert は現物 1 枚に 1 つなので、 既知なら二重に押さえない
    if vision["cert"] in claimed["certs"]:
        rej["already_claimed_cert"] += 1
        return None

    return _build_candidate(url, detail, q, images, vision)


def _build_candidate(url, detail, q, images, vision, cert_readable: bool = True) -> dict:
    """候補 dict を組み立てる.

    cert_readable=False は 「鑑定番号が写真から読めなかった」 = I列空欄で入れる分。
    """
    return {
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
        "cert_readable": cert_readable,
    }


def build_sheet_items(kept: list[dict], unreadable: list[dict]) -> list[dict]:
    """スプシ書込用 item を作る (純関数).

    - kept: 事前ゲート通過分 → I列に cert を入れる (出品くんの入口)
    - unreadable: 鑑定番号が読めなかった分 → **I列は空欄** (目視で確認するため)
    """
    def _one(c: dict, cert: str) -> dict:
        return {
            "url": c["url"], "title": c.get("title"), "condition": c.get("condition"),
            "price_jpy": c.get("price_jpy"), "image_urls": c.get("image_urls"),
            "description": c.get("description"),
            "cert": cert,  # I 列 (本番へ移した時の出品くんの入口)
        }

    items = [_one(c, (c.get("vision") or {}).get("cert") or "") for c in kept]
    items += [_one(c, "") for c in unreadable]
    return items

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


def _dump(payload: dict, path: Path, quiet: bool = False) -> None:
    """JSON へ書き出す。 quiet=True は 途中セーブ (毎回ログを出すと埋まるため黙る).

    ★同じ path に上書きし続ける。 途中セーブの目的は「落ちた時に続きから再開できること」
    なので、 常に最新の 1 ファイルがあれば足りる。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    # 書込中に落ちても前回分を壊さない (tmp に書いてから置換)
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    if not quiet:
        _log(f"[FILE] {path}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--price-min", type=int, default=3000)
    ap.add_argument("--price-max", type=int, default=100000)
    ap.add_argument("--min-rating", type=int, default=100, help="セラー評価数の下限")
    ap.add_argument("--no-identity", action="store_true", help="本人確認済 要件を外す")
    ap.add_argument("--cap-per-keyword", type=int, default=100)
    ap.add_argument("--max-details", type=int, default=0, help="詳細フェッチ上限 (0=無制限)")
    ap.add_argument("--keywords", nargs="*", default=None,
                    help="上書きキーワード (既定は弾コードから自動生成)")
    ap.add_argument("--games", nargs="*", default=None,
                    choices=list(psa_search_terms.GAMES),
                    help=f"対象ゲーム (既定=全部: {', '.join(psa_search_terms.GAMES)})")
    ap.add_argument("--keyword-interval", type=float, default=8.0,
                    help="語間の待機秒 (2026-08-17 実測: 8秒空ければ件数が落ちない)")
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--manual", action="store_true",
                    help="フリマアシスト手動click で volume 突破 (非headless必須)")
    ap.add_argument("--psa-interval", type=float, default=300.0,
                    help="PSA 照合の間隔秒 (429 回避。 2026-08-17 実測で数発/分は即 429)")
    ap.add_argument("--min-signals", type=int, default=2,
                    help="ラベル一致に要求する系統数 (既定2 = 1桁誤読を落とす)")
    ap.add_argument("--verify-from-json", default=None,
                    help="収集をやり直さず、 JSON の未照合分だけ PSA 照合し直す")
    ap.add_argument("--label", default="psa10",
                    help="中間スプシ tab suffix (= mercari_<label>)")
    ap.add_argument("--verify", action="store_true",
                    help="Harvest 側でも PSA 公式照会して先に確定させる "
                         "(既定 OFF = 出品くん側に 1 本化)")
    ap.add_argument("--no-dedupe", action="store_true",
                    help="本番スプシとの重複チェックを行わない (調査用)")
    # ★長時間走行の作業を捨てないための3点 (2026-08-17: 145件分を失った事故の対策)
    ap.add_argument("--save-every", type=int, default=10,
                    help="何件ごとに途中セーブするか (既定10)")
    ap.add_argument("--max-consecutive-errors", type=int, default=3,
                    help="連続失敗が何回でドライバを作り直すか (既定3)")
    ap.add_argument("--resume-from-json", default=None,
                    help="前回の JSON から再開 (処理済 URL を飛ばす)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    if args.verify_from_json:
        path = Path(args.verify_from_json)
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["verify_stats"] = verify_all(payload["candidates"], args.psa_interval,
                                             args.min_signals)
        _dump(payload, path)
    else:
        # ★保存先を collect() に渡す = 走行中ずっと途中セーブされる。
        # 再開時は同じファイルを上書きし続けるので、 何度落ちても続きから積み上がる。
        resume = None
        if args.resume_from_json:
            path = Path(args.resume_from_json)
            resume = json.loads(path.read_text(encoding="utf-8"))
        else:
            path = DUMP_DIR / f"mercari_psa10_{datetime.now():%Y%m%dT%H%M%S}.json"
        payload = collect(args, dump_path=path, resume=resume)
        _dump(payload, path)
        if args.verify:
            payload["verify_stats"] = verify_all(payload["candidates"],
                                                 args.psa_interval, args.min_signals)
            _dump(payload, path)

    cands = payload["candidates"]
    if payload.get("verify_stats"):
        # --verify を通した時は 公式照会で確定した物だけ渡す
        kept = [c for c in cands if (c.get("psa") or {}).get("ok")]
        _log(f"確定 (公式照会済): {len(kept)}/{len(cands)} 件 "
             f"/ 内訳={payload['verify_stats']}")
    else:
        # 既定: 公式照会は出品くん側の 1 本化に任せる。 Harvest は事前ゲート通過分を渡す
        kept = cands
        _log(f"候補 (事前ゲート通過): {len(kept)} 件 — 公式照会と確定は出品くん側で実施")

    for c in kept:
        _log(f"  cert={c['vision']['cert']} ¥{c.get('price_jpy')} "
             f"{(c.get('title') or '')[:32]} {c['url']}")

    # 鑑定番号が読めなかった分 (I列空欄で投入 = 目視で確認する。 2026-08-18 user 指示)
    unreadable = payload.get("unreadable") or []
    if unreadable:
        _log(f"番号読めず (I列空欄で投入): {len(unreadable)} 件 — 目視で確認")
        for c in unreadable:
            _log(f"  cert=?? ¥{c.get('price_jpy')} "
                 f"{(c.get('title') or '')[:32]} {c['url']}")

    if args.dry_run:
        _log("dry-run → 書込なし")
        return 0
    if not kept and not unreadable:
        _log("0 件 → 書込なし")
        return 0

    from sheet_writer_mercari_search import append_mercari_search_items  # noqa: PLC0415
    items = build_sheet_items(kept, unreadable)
    res = append_mercari_search_items(items, label=args.label)
    _log(f"[SHEET] {res}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
