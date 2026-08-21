"""run_harvest_gashapon_line - **公式の商品ラインを起点に** 仕入元を探す.

2026-08-21 新設 (user 依頼「公式にあるめじるしを出品したい」)。

これまでの `run_harvest_rakuten_gacha.py` は **店を先に決めて**その店内を探す。
めじるしアクセサリーのように「公式には84商品あるが、 楽天では12店にばらけていて
1店あたり数商品しかない」ものは、 店を1つずつ登録しても集まらない (実測)。

そこで探し方を逆にする:

  ① 公式 (gashapon.jp) の一覧から **商品名の一覧** を取る (名前 + jan_code)
  ② 商品名ごとに **楽天全体**を検索する (店は問わない)
  ③ 公式の商品名がタイトルに丸ごと入っている物だけ候補にする (別商品を掴まない)
  ④ 商品ページを開いて 即納 / 送料 / 画像 / 説明 を取る
  ⑤ 公式の jan_code で **対象年齢**を確認する (15才未満は入れない)

使い方:
  python run_harvest_gashapon_line.py --line めじるし --limit 30
  python run_harvest_gashapon_line.py --line めじるし --dry-run
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

import gacha_age  # noqa: E402
from scrapers import rakuten_item, rakuten_search  # noqa: E402

DUMP_DIR = ROOT / "debug"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass


def _log(m: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def official_products(line: str) -> list[tuple[str, str]]:
    """公式カタログから (商品名, jan_code) を返す. line で名前を絞る."""
    return [(disp, code) for _, code, disp in gacha_age.fetch_catalog()
            if not line or line in disp]


def title_matches(official: str, title: str) -> bool:
    """楽天のタイトルが **その公式商品** を指しているか (fail-closed).

    公式の商品名 (記号と空白を落とした形) がタイトルに丸ごと入っている時だけ True。
    部分一致で緩めると 同じシリーズの別弾 を掴む。
    """
    o = gacha_age.normalize_name(official)
    return len(o) >= 6 and o in gacha_age.normalize_name(title)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--line", default="めじるし", help="公式の商品名に含まれる語")
    ap.add_argument("--limit", type=int, default=30, help="公式商品を何件まで見るか")
    ap.add_argument("--max-pages", type=int, default=2, help="1商品あたりの検索ページ数")
    ap.add_argument("--label", default="", help="書き込むタブ (既定は line 名)")
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    products = official_products(args.line)
    _log(f"公式カタログの '{args.line}': {len(products)} 商品 (先頭 {args.limit} 件を見る)")
    if not products:
        return 0
    products = products[:args.limit]

    known: set = set()
    claimed: set = set()
    if not args.dry_run:
        try:
            from sheet_writer import load_claimed_supply
            from sheet_writer_mercari_seller import open_seller_staging_sheet
            from sheet_writer_rakuten import load_keys_all_tabs
            claimed = load_claimed_supply()["urls"]
            known = load_keys_all_tabs(open_seller_staging_sheet())
            _log(f"本番で押さえ済 {len(claimed)} / 中間スプシ済 {len(known)}")
        except Exception as e:  # noqa: BLE001
            _log(f"⚠️ 既存キーを読めず: {type(e).__name__}")

    from sheet_writer_rakuten import dedupe_key
    cands: list[dict] = []
    no_supply: list[str] = []
    for name, code in products:
        try:
            rows = rakuten_search.search_mall(f"{name} コンプ", max_pages=args.max_pages)
        except Exception as e:  # noqa: BLE001
            _log(f"  ⚠️ '{name[:24]}' 検索失敗 {type(e).__name__}")
            continue
        hit = []
        for r in rows:
            t = r["title"]
            if not title_matches(name, t):
                continue
            if not rakuten_search.is_complete_set(t) or not rakuten_search.is_toy(t):
                continue
            if rakuten_search.looks_preorder(t) or rakuten_search.looks_soldout(t):
                continue
            k = dedupe_key(r["url"])
            if k in claimed or k in known or r["url"] in claimed:
                continue
            r["official_name"] = name
            r["jan_code"] = code
            hit.append(r)
        if hit:
            cands.extend(hit)
        else:
            no_supply.append(name)
        _log(f"  {name[:34]}: 候補 {len(hit)}")
    _log(f"候補 {len(cands)} 件 / 楽天に無かった商品 {len(no_supply)} 件")
    if args.dry_run or not cands:
        return 0

    from scrapers import mercari_seller as MS
    from scrapers._chrome_util import kill_chrome_for_profile
    killed = kill_chrome_for_profile(MS.CHROME_PROFILE_DIR_ANON)
    if killed:
        _log(f"前回の残留 chrome を {killed} 個 片付けました")
    driver = MS.create_anonymous_driver(headless=args.headless)
    label = args.label or args.line
    kept: list[dict] = []
    rej: dict[str, int] = {}
    ts = datetime.now().strftime("%Y%m%dT%H%M%S")
    pending: list[dict] = []

    def _flush(rows: list[dict]) -> bool:
        if not rows:
            return True
        from sheet_writer_rakuten import append_items
        try:
            _log(f"  [SHEET] {append_items(rows, label=label, known_keys=known)}")
            return True
        except Exception as e:  # noqa: BLE001
            _log(f"  ⚠️ 書込失敗 ({type(e).__name__}) → 溜めたまま次に回す")
            return False

    try:
        for c in cands:
            detail = rakuten_item.fetch_detail(driver, c["url"])
            if detail is None:
                rej["fetch_fail"] = rej.get("fetch_fail", 0) + 1
                continue
            if not detail["in_stock_now"]:
                rej[detail["reason"]] = rej.get(detail["reason"], 0) + 1
                continue
            if detail.get("shipping_fee") is None or not detail.get("total_jpy"):
                rej["fee_unknown"] = rej.get("fee_unknown", 0) + 1
                continue
            age = gacha_age.fetch_age_by_code(c["jan_code"])
            if gacha_age.is_too_young(age):
                rej["age_ng"] = rej.get("age_ng", 0) + 1
                _log(f"  対象年齢 {age}才 → 除外 {c['official_name'][:28]}")
                continue
            item = dict(c)
            item.update({k: detail[k] for k in
                         ("price_jpy", "image_urls", "description", "shipping",
                          "shipping_fee", "total_jpy")})
            item["title"] = detail["title"] or c["title"]
            if age is not None:
                item["description"] = f"{item['description']} 対象年齢: {age}才以上".strip()
            kept.append(item)
            pending.append(item)
            _log(f"  即納 {len(kept)}件目 ¥{item['total_jpy']} [{c['shop']}] "
                 f"{item['title'][:34]}")
            if len(pending) >= 5 and _flush(pending):
                pending = []
            time.sleep(1.0)
    finally:
        if not _flush(pending) and pending:
            path = DUMP_DIR / f"gashapon_line_unwritten_{ts}.json"
            path.write_text(json.dumps({"unwritten": pending}, ensure_ascii=False),
                            encoding="utf-8")
            _log(f"  ⚠️ 書けなかった {len(pending)}件を {path.name} に退避")
        try:
            driver.quit()
        except Exception:  # noqa: BLE001
            pass
    _log(f"完了: 即納 {len(kept)} 件 / 落とした内訳={rej}")
    (DUMP_DIR / f"gashapon_line_{args.line}_{ts}.json").write_text(
        json.dumps({"kept": kept, "no_supply": no_supply, "reject": rej},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
