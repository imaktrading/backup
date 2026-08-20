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

from gacha_age import fetch_age, fetch_age_by_title, is_too_young  # noqa: E402
from gacha_maker import ALLOWED_MAKERS, is_allowed, resolve_maker  # noqa: E402
from scrapers import rakuten_item, rakuten_search  # noqa: E402

DUMP_DIR = ROOT / "debug"
SHOPS = ("auc-toysanta", "auc-yuyou", "mirakikaku", "smltrading")
# ★jugem2020 は外した (2026-08-20)。 検索には出るのに商品ページが全部 404 で、
#   開くと店トップへ転送される。 集めた32件は全滅だった。
# kidsroom は 2026-08-20 に外した (どの検索でも0件)。
# jugem2020 / smltrading は バンダイのコンプ品が多い店として追加。

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


def build_themes(args) -> list[tuple[str, str, int]]:
    """走行の枠を決める. `--maker` があれば そのメーカー1本に置き換える.

    2026-08-20: 5メーカーに絞った以降、 テーマ検索 (サンリオ/めじるし/…) では
    **メーカー名で探していないので取りこぼす**。 実測でブシロード258件・バンダイ240件が
    テーマ4本には1件も出てこなかった。 メーカー名で引く方が素直。
    """
    if args.keyword:
        return [(args.keyword, args.keyword, args.quota or 100)]
    if args.maker:
        return [(args.maker, f"{args.maker} コンプリート", args.quota or 100)]
    return THEMES


def collect_candidates(args, claimed_urls: set) -> tuple[list[dict], dict]:
    """検索とタイトル判定まで (無料の範囲) をやる."""
    from sheet_writer_rakuten import dedupe_key  # noqa: PLC0415

    rej = {"not_complete": 0, "not_toy": 0, "preorder_title": 0,
           "already_claimed": 0, "dup": 0, "maker_ng": 0}
    out: list[dict] = []
    seen: set[str] = set()
    for label, keyword, quota in build_themes(args):
        picked = 0
        cap = quota * args.oversample
        # 1店で枠を食い切らないよう **店ごとに上限**を置く。
        # 2026-08-20: これが無いと auc-yuyou だけで枠が埋まり、
        # 後ろの店 (jugem2020 等) を一度も検索しないまま終わっていた
        per_shop = max(1, int(cap / (1 if args.shop else len(SHOPS))) + 1)
        for shop in (args.shop,) if args.shop else SHOPS:
            if picked >= cap:
                break
            picked_here = 0
            try:
                rows = rakuten_search.search_shop(
                    shop, keyword, max_pages=args.max_pages,
                    free_shipping=args.free_shipping_only,
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
                if rakuten_search.looks_soldout(r["title"]):
                    # 【品切中】等がタイトルに入る店がある (auc-toysanta)
                    rej["soldout_title"] = rej.get("soldout_title", 0) + 1
                    continue
                if key in claimed_urls or r["url"] in claimed_urls:
                    rej["already_claimed"] += 1
                    continue
                maker = resolve_maker(r["title"])
                if args.maker:
                    # 狙い撃ちモード: タイトルで **別のメーカーと分かる物**だけ落とす。
                    # タイトルにメーカーを書かない店 (mirakikaku / auc-toysanta) は
                    # 商品説明の「メーカー：」で決まるので、詳細まで持っていく。
                    # (店ごとの上限があるので詳細取得が膨らみすぎることはない)
                    if maker and maker != args.maker:
                        rej["maker_ng"] += 1
                        continue
                elif maker and maker not in ALLOWED_MAKERS:
                    # タイトルでメーカーが分かって対象外 → ここで落とす (詳細を見に行かない)
                    rej["maker_ng"] += 1
                    continue
                seen.add(key)
                r["theme"] = label
                out.append(r)
                picked += 1
                picked_here += 1
                if picked >= cap or picked_here >= per_shop:
                    break
        _log(f"テーマ '{label}': 候補 {picked} 件 (枠 {quota})")
    return out, rej


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-pages", type=int, default=2, help="1店1語あたりの検索ページ数")
    ap.add_argument("--oversample", type=float, default=2.0,
                    help="枠の何倍まで候補を集めるか (配送予定で落ちる分の余裕)")
    ap.add_argument("--label", default="gacha", help="中間スプシ tab (= rakuten_<label>)")
    ap.add_argument("--shop", default="", help="この店だけを見る (例 auc-toysanta)")
    ap.add_argument("--keyword", default="", help="検索語を指定する (店独自の言い回し用)")
    ap.add_argument("--maker", default="",
                    help="メーカー名で狙い撃ちする (例 バンダイ)。 テーマ枠は使わない。"
                         " auc-yuyou はタイトルにメーカー名を書くので、"
                         " **タイトルでそのメーカーと分かる物だけ**を候補にする")
    ap.add_argument("--quota", type=int, default=0, help="--maker 時に集める上限件数")
    ap.add_argument("--sheet-every", type=int, default=5,
                    help="何件ごとにスプシへ書くか (こけた時に失う分を小さくする)")
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--no-dedupe", action="store_true", help="本番との重複チェックをしない")
    ap.add_argument("--free-shipping-only", action="store_true",
                    help="送料無料の商品だけにする (既定は 送料込みの総額で扱う)")
    ap.add_argument("--include-paid-shipping", action="store_true",
                    help="送料有料の商品も対象にする (既定は送料無料のみ = 表示価格が総額)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    claimed: set = set()
    if not args.no_dedupe:
        from sheet_writer import load_claimed_supply  # noqa: PLC0415
        claimed = load_claimed_supply()["urls"]
        _log(f"本番で押さえ済の仕入元 URL: {len(claimed)} 件")

    known: set = set()
    if not args.dry_run:
        try:
            from sheet_writer_mercari_seller import open_seller_staging_sheet  # noqa: PLC0415
            from sheet_writer_rakuten import load_keys_all_tabs  # noqa: PLC0415
            known = load_keys_all_tabs(open_seller_staging_sheet())
            _log(f"中間スプシに既にある楽天商品: {len(known)} 件")
        except Exception as e:  # noqa: BLE001
            _log(f"⚠️ 既存キーを読めず: {type(e).__name__}")

    # 既に集めた物は **詳細を見に行かない** (1件6秒が丸ごと無駄になる)
    cands, rej = collect_candidates(args, claimed | known)
    _log(f"検索完了: 候補 {len(cands)} 件 / 落とした内訳={rej}")
    if not cands:
        _log("候補 0 件 → 終了")
        return 0

    ts = datetime.now().strftime("%Y%m%dT%H%M%S")
    dump_path = DUMP_DIR / f"rakuten_gacha_{ts}.json"

    # ④ 配送予定で即納だけ残す (ここだけブラウザ)
    from scrapers import mercari_seller as MS  # noqa: PLC0415  (匿名ドライバを流用)
    from scrapers._chrome_util import kill_chrome_for_profile  # noqa: PLC0415
    # 前回の残骸が profile を掴んでいると driver が起動できない (実測: 候補90件が全滅)
    killed = kill_chrome_for_profile(MS.CHROME_PROFILE_DIR_ANON)
    if killed:
        _log(f"前回の残留 chrome を {killed} 個 片付けました")
    driver = MS.create_anonymous_driver(headless=args.headless)
    kept: list[dict] = []
    failed: list[str] = []
    quota_left = {label: quota for label, _, quota in build_themes(args)}
    detail_rej = {"preorder": 0, "no_shipping_info": 0, "fetch_fail": 0, "quota_full": 0,
                  "maker_ng": 0, "age_ng": 0}
    def _flush(rows: list[dict]) -> bool:
        """書けたら True。 **書けなかったら False を返し、 呼出側は溜めたまま次に回す**。

        2026-08-20 修正: 以前は失敗しても呼出側が pending を捨てていたため、
        1回の ConnectionError で **10件が黙って消えていた** (実測)。
        取りこぼしを黙って落とすのは禁止 (グローバル規約「silent drop 禁止」)。
        """
        if args.dry_run or not rows:
            return True
        from sheet_writer_rakuten import append_items  # noqa: PLC0415
        try:
            res = append_items(rows, label=args.label, known_keys=known)
            _log(f"  [SHEET] {res}")
            return True
        except Exception as e:  # noqa: BLE001 - 書込失敗で走行を殺さない
            _log(f"  ⚠️ スプシ書込に失敗 ({type(e).__name__}) → 溜めたまま次に回す ({len(rows)}件)")
            return False

    pending: list[dict] = []
    consecutive_fail = 0     # ドライバが死ぬと全件 fetch_fail になるので見張る
    restarts = 0
    try:
        for i, c in enumerate(cands, 1):
            if quota_left.get(c["theme"], 0) <= 0:
                detail_rej["quota_full"] += 1
                continue
            detail = rakuten_item.fetch_detail(driver, c["url"])
            if detail is None:
                detail_rej["fetch_fail"] += 1
                failed.append(c["url"])
                consecutive_fail += 1
                # ★連続で失敗する = ドライバが死んでいる。 実測 2026-08-20 では
                #   これに気づかず 90件を空振りし続けて走行が終わっていた。
                #   **溜めた分を先に保存してから** 再起動を試す。
                if consecutive_fail >= 5:
                    if pending and _flush(pending):
                        pending = []
                    if restarts < 2:
                        restarts += 1
                        _log(f"  ⚠️ 連続 {consecutive_fail} 件失敗 → ドライバを再起動 "
                             f"({restarts}回目)")
                        try:
                            driver.quit()
                        except Exception:  # noqa: BLE001
                            pass
                        kill_chrome_for_profile(MS.CHROME_PROFILE_DIR_ANON)
                        driver = MS.create_anonymous_driver(headless=args.headless)
                        consecutive_fail = 0
                    else:
                        _log("  ⚠️ 再起動しても直らないので中断します "
                             f"(ここまでの {len(kept)}件は保存済)")
                        break
                continue
            consecutive_fail = 0
            if not detail["in_stock_now"]:
                detail_rej[detail["reason"]] = detail_rej.get(detail["reason"], 0) + 1
                continue
            if detail.get("shipping_fee") is None or not detail.get("total_jpy"):
                # 仕入原価 (商品価格 + 送料) が確定しない物は採らない (推測で足さない)
                detail_rej["fee_unknown"] = detail_rej.get("fee_unknown", 0) + 1
                continue
            item = dict(c)
            item.update({k: detail[k] for k in
                         ("price_jpy", "image_urls", "description", "shipping",
                          "shipping_fee", "total_jpy")})
            item["title"] = detail["title"] or c["title"]
            if not is_allowed(item["title"], item["description"]):
                # 商品説明の「メーカー：」まで見て、対象メーカーでなければ採らない
                detail_rej["maker_ng"] += 1
                continue
            if resolve_maker(item["title"], item["description"]) == "バンダイ":
                # バンダイだけ 対象年齢を公式で確認できる (JAN 直引き)。
                # 15才未満と**分かった**物は入れない。読めなければ目視に回す
                age = fetch_age(detail.get("jan") or "")
                if age is None:
                    # JAN を出さない店 (実測 jugem2020) は 公式カタログの商品名で引く
                    age = fetch_age_by_title(item["title"])
                if is_too_young(age):
                    detail_rej["age_ng"] += 1
                    _log(f"  対象年齢 {age}才 → 除外 {item['title'][:30]}")
                    continue
                if age is not None:
                    item["description"] = f"{item['description']} 対象年齢: {age}才以上".strip()
            kept.append(item)
            pending.append(item)
            quota_left[c["theme"]] -= 1
            _log(f"  即納 {len(kept)}件目 [{c['theme']}] ¥{item['total_jpy']}"
                 f"(本体{item['price_jpy']}+送料{item['shipping_fee']}) "
                 f"{item['shipping']} {item['title'][:34]}")
            if len(pending) >= args.sheet_every and _flush(pending):
                pending = []
            _dump({"kept": kept, "failed_urls": failed, "detail_reject": detail_rej,
                   "search_reject": rej}, dump_path)
            if all(v <= 0 for v in quota_left.values()):
                _log("全テーマの枠が埋まりました")
                break
            time.sleep(1.0)
    finally:
        if not _flush(pending) and pending:
            # 最後まで書けなかった分は **消さずに** ファイルへ落として、次回に回す
            leftover = DUMP_DIR / f"rakuten_gacha_unwritten_{ts}.json"
            _dump({"unwritten": pending}, leftover)
            _log(f"  ⚠️ 書けなかった {len(pending)}件を {leftover.name} に退避 (要再投入)")
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
