"""run_harvest_rakuten_gacha - 楽天3店から ガチャポンのコンプ品 (即納のみ) を収集.

2026-08-19 新設 (user 依頼)。

流れ (安い順に落として、 最後に確証を取る = user 確定の方針):
  ① 店舗内検索 (HTTP・無料) を **新着順**で引く
  ② タイトルで落とす: コンプ品でない / 予約表記あり
  ③ 本番 (HIGH/LOW) に既にある仕入元 URL を落とす
  ④ 残りだけ **ブラウザで開いて配送予定を読む** (1件6秒)。
     発送日が読めた物だけ即納として採用。 読めなければ **入れない** (HQ 指示: 迷ったら落とす)
  ⑤ 中間スプシ `rakuten_gacha` に append (M列に価格 / R列に カプセルトイ)

テーマ別の枠は user 確定 (2026-08-19): サンリオ40 / めじるし30 / 猫・動物20 / お菓子10。
初回は 50〜100件 (HQ 指示: 一気に入れない。 出品側の処理能力に合わせる)。

使い方:
  python run_harvest_rakuten_gacha.py --dry-run
  python run_harvest_rakuten_gacha.py
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

from scrapers import rakuten_item, rakuten_search  # noqa: E402

DUMP_DIR = ROOT / "debug"
SHOPS = ("auc-yuyou", "kidsroom", "mirakikaku")

# テーマ = (ラベル, 検索語, 枠). 枠 = 採用する上限件数
THEMES = [
    ("サンリオ", "サンリオ コンプリート", 40),
    ("めじるし", "めじるし コンプリート", 30),
    ("猫・動物", "動物 フィギュア コンプリート", 20),
    ("お菓子ミニチュア", "ミニチュア お菓子 コンプリート", 10),
]

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass


def _log(m: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def _dump(payload: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def collect_candidates(args, claimed_urls: set) -> tuple[list[dict], dict]:
    """検索とタイトル判定まで (無料の範囲) をやる."""
    from sheet_writer_rakuten import dedupe_key  # noqa: PLC0415

    rej = {"not_complete": 0, "not_toy": 0, "preorder_title": 0,
           "already_claimed": 0, "dup": 0}
    out: list[dict] = []
    seen: set[str] = set()
    for label, keyword, quota in THEMES:
        picked = 0
        for shop in SHOPS:
            if picked >= quota * args.oversample:
                break
            try:
                rows = rakuten_search.search_shop(
                    shop, keyword, max_pages=args.max_pages,
                    free_shipping=not args.include_paid_shipping,
                    progress=lambda m: _log(f"  収集 {m}"))
            except Exception as e:  # noqa: BLE001 - 1店が落ちても他店は続ける
                _log(f"  ⚠️ {shop} '{keyword}' 検索失敗: {type(e).__name__}")
                continue
            for r in rows:
                key = dedupe_key(r["url"])
                if key in seen:
                    rej["dup"] += 1
                    continue
                if not rakuten_search.is_complete_set(r["title"]):
                    rej["not_complete"] += 1
                    continue
                if not rakuten_search.is_toy(r["title"]):
                    # 実際の食べ物は扱わない (user 指摘 2026-08-19)。 ミニチュアは可
                    rej["not_toy"] += 1
                    continue
                if rakuten_search.looks_preorder(r["title"]):
                    rej["preorder_title"] += 1
                    continue
                if key in claimed_urls or r["url"] in claimed_urls:
                    rej["already_claimed"] += 1
                    continue
                seen.add(key)
                r["theme"] = label
                out.append(r)
                picked += 1
                if picked >= quota * args.oversample:
                    break
        _log(f"テーマ '{label}': 候補 {picked} 件 (枠 {quota})")
    return out, rej


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-pages", type=int, default=2, help="1店1語あたりの検索ページ数")
    ap.add_argument("--oversample", type=float, default=2.0,
                    help="枠の何倍まで候補を集めるか (配送予定で落ちる分の余裕)")
    ap.add_argument("--label", default="gacha", help="中間スプシ tab (= rakuten_<label>)")
    ap.add_argument("--sheet-every", type=int, default=10, help="何件ごとにスプシへ書くか")
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--no-dedupe", action="store_true", help="本番との重複チェックをしない")
    ap.add_argument("--include-paid-shipping", action="store_true",
                    help="送料有料の商品も対象にする (既定は送料無料のみ = 表示価格が総額)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    claimed: set = set()
    if not args.no_dedupe:
        from sheet_writer import load_claimed_supply  # noqa: PLC0415
        claimed = load_claimed_supply()["urls"]
        _log(f"本番で押さえ済の仕入元 URL: {len(claimed)} 件")

    cands, rej = collect_candidates(args, claimed)
    _log(f"検索完了: 候補 {len(cands)} 件 / 落とした内訳={rej}")
    if not cands:
        _log("候補 0 件 → 終了")
        return 0

    ts = datetime.now().strftime("%Y%m%dT%H%M%S")
    dump_path = DUMP_DIR / f"rakuten_gacha_{ts}.json"

    # ④ 配送予定で即納だけ残す (ここだけブラウザ)
    from scrapers import mercari_seller as MS  # noqa: PLC0415  (匿名ドライバを流用)
    driver = MS.create_anonymous_driver(headless=args.headless)
    kept: list[dict] = []
    failed: list[str] = []
    quota_left = {label: quota for label, _, quota in THEMES}
    detail_rej = {"preorder": 0, "no_shipping_info": 0, "fetch_fail": 0, "quota_full": 0}
    known: set = set()
    if not args.dry_run:
        try:
            from sheet_writer_mercari_seller import open_seller_staging_sheet  # noqa: PLC0415
            from sheet_writer_rakuten import load_keys_all_tabs  # noqa: PLC0415
            known = load_keys_all_tabs(open_seller_staging_sheet())
            _log(f"中間スプシに既にある楽天商品: {len(known)} 件")
        except Exception as e:  # noqa: BLE001
            _log(f"⚠️ 既存キーを読めず: {type(e).__name__}")

    def _flush(rows: list[dict]) -> None:
        if args.dry_run or not rows:
            return
        from sheet_writer_rakuten import append_items  # noqa: PLC0415
        try:
            res = append_items(rows, label=args.label, known_keys=known)
            _log(f"  [SHEET] {res}")
        except Exception as e:  # noqa: BLE001 - 書込失敗で走行を殺さない
            _log(f"  ⚠️ スプシ書込に失敗 ({type(e).__name__}) → 後でまとめて書く")

    pending: list[dict] = []
    try:
        for i, c in enumerate(cands, 1):
            if quota_left.get(c["theme"], 0) <= 0:
                detail_rej["quota_full"] += 1
                continue
            detail = rakuten_item.fetch_detail(driver, c["url"])
            if detail is None:
                detail_rej["fetch_fail"] += 1
                failed.append(c["url"])
                continue
            if not detail["in_stock_now"]:
                detail_rej[detail["reason"]] = detail_rej.get(detail["reason"], 0) + 1
                continue
            item = dict(c)
            item.update({k: detail[k] for k in
                         ("price_jpy", "image_urls", "description", "shipping")})
            item["title"] = detail["title"] or c["title"]
            kept.append(item)
            pending.append(item)
            quota_left[c["theme"]] -= 1
            _log(f"  即納 {len(kept)}件目 [{c['theme']}] ¥{item['price_jpy']} "
                 f"{item['shipping']} {item['title'][:34]}")
            if len(pending) >= args.sheet_every:
                _flush(pending)
                pending = []
            _dump({"kept": kept, "failed_urls": failed, "detail_reject": detail_rej,
                   "search_reject": rej}, dump_path)
            if all(v <= 0 for v in quota_left.values()):
                _log("全テーマの枠が埋まりました")
                break
            time.sleep(1.0)
    finally:
        _flush(pending)
        _dump({"kept": kept, "failed_urls": failed, "detail_reject": detail_rej,
               "search_reject": rej}, dump_path)
        try:
            driver.quit()
        except Exception:
            pass

    _log(f"完了: 即納 {len(kept)} 件 / 詳細で落とした内訳={detail_rej}")
    _log(f"[FILE] {dump_path}")
    if failed:
        _log(f"⚠️ 要対応: ページを開けなかった {len(failed)} 件 (未判定)")
    if args.dry_run:
        _log("dry-run → 書込なし")
    return 0


if __name__ == "__main__":
    sys.exit(main())
