"""run_harvest_yodobashi - ヨドバシ.com から G-shock を収集し中間スプシに append.

2026-07-26 新設 (user 依頼)。 Amazon (`run_harvest_amazon_search.py`) の姉妹ランナー。
在庫あり (お届け表記) の G-shock 単品のみを keep し、 `yodobashi_<label>` タブに append。
末尾で Amazon タブ (`amazon_<label>`) と型番 (AI 列) を突合し仕入元差分を報告する。

keep gate (fail-closed):
  - 在庫あり (yodobashi_search_http.is_in_stock) — 取寄/廃番/予約は skip
  - G-shock ブランド (is_gshock)
  - ギフトセット/ペアウォッチ除外 (amazon_search_http.is_gift_or_pair_set と単一ソース共有)

使い方:
  python run_harvest_yodobashi.py --dry-run          # 収集のみ (スプシ書込なし) + 差分
  python run_harvest_yodobashi.py                     # 収集 + スプシ append + 差分
  python run_harvest_yodobashi.py --url "<検索URL>"   # 検索 URL 上書き (既定は メンズフィルタ)
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from scrapers import yodobashi_search_http as Y  # noqa: E402
from scrapers.amazon_search_http import is_gift_or_pair_set  # noqa: E402

# user 提供 (2026-07-26): 販売終了除外 + メンズ + カシオ CASIO G-SHOCK ジーショック
DEFAULT_SEARCH_URL = (
    "https://www.yodobashi.com/category/18457/18458/m0000008179/"
    "?spcs=Specvaluecode_500000000000326001_0001_0000000173_0000001591&word=G-shock"
)
DUMP_DIR = Path(r"c:\dev\iMak_data\catalog\_amazon_jp_dumps")


def _log(m: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def _load_amazon_models(label: str) -> dict:
    """amazon_<label> タブの AI(型番) 列を {model: title} で読む (差分照合用).

    読めない (タブ無し/認証失敗) 場合は空 dict (= 差分は yodobashi 全件 new 扱い)。
    """
    try:
        from sheet_writer_amazon import COL_KEY, COL_TITLE  # noqa: PLC0415
        from sheet_writer_mercari_seller import open_seller_staging_sheet  # noqa: PLC0415
        sh = open_seller_staging_sheet()
        ws = sh.worksheet(f"amazon_{label}")
        vals = ws.get_all_values()
        out = {}
        for row in vals[1:]:
            key = (row[COL_KEY - 1].strip() if len(row) >= COL_KEY else "")
            title = (row[COL_TITLE - 1].strip() if len(row) >= COL_TITLE else "")
            if key:
                out[key.upper()] = title
        return out
    except Exception as e:  # noqa: BLE001
        _log(f"[diff] amazon_{label} 読取不可 ({type(e).__name__}) → 差分は yodobashi 全件 new 扱い")
        return {}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=DEFAULT_SEARCH_URL, help="ヨドバシ検索 URL (既定=メンズG-shock)")
    ap.add_argument("--label", default="gshock", help="tab suffix (= yodobashi_<label>)")
    ap.add_argument("--dry-run", action="store_true", help="スプシ書込なし (収集+差分のみ)")
    ap.add_argument("--max-pages", type=int, default=Y.DEFAULT_MAX_PAGES)
    ap.add_argument("--include-out-of-stock", action="store_true",
                    help="在庫あり以外 (取寄/廃番) も含める (既定=在庫ありのみ)")
    args = ap.parse_args(argv)

    _log(f"開始: label={args.label!r} dry_run={args.dry_run}")
    _log(f"  URL: {args.url}")

    session = Y.create_session()
    res = Y.collect_gshock_products(
        session, args.url, max_pages=args.max_pages,
        progress_callback=lambda p, n, m: _log(f"  {m}"),
    )
    if res["blocked"]:
        # fail-OPEN 対策: page1=0件 = ブロック疑い。 0件を「新規なし」と誤報告しない。
        _log("❌ page1=0件 = ブロック疑い → 異常終了 (exit 1)。 時間を空けて再実行を。")
        return 1

    products = res["products"]
    _log(f"収集: {len(products)} 件 ({res['pages_scanned']} ページ)")

    # keep gate (fail-closed)
    kept, rej = [], {"not_gshock": 0, "out_of_stock": 0, "gift_pair": 0, "no_model": 0}
    for p in products:
        if not p["is_gshock"]:
            rej["not_gshock"] += 1
            continue
        if not args.include_out_of_stock and not p["in_stock"]:
            rej["out_of_stock"] += 1
            continue
        if is_gift_or_pair_set(p["title"]):
            rej["gift_pair"] += 1
            continue
        if not p["model_number"]:
            rej["no_model"] += 1  # 型番不明 = 照合不能 → fail-closed で skip
            continue
        kept.append(p)
    _log(f"keep={len(kept)} / reject={rej}")

    # JSON dump
    DUMP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%dT%H%M%S")
    dump_path = DUMP_DIR / f"yodobashi_{args.label}_{ts}.json"
    dump_path.write_text(
        json.dumps({"collected": len(products), "kept": kept, "reject": rej},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    _log(f"[FILE] JSON dump: {dump_path}")

    # Amazon 差分照合 (型番ベース)
    amazon_models = _load_amazon_models(args.label)
    ydb_models = {k["model_number"].upper() for k in kept}
    only_ydb = sorted(ydb_models - set(amazon_models))
    both = sorted(ydb_models & set(amazon_models))
    only_amz = sorted(set(amazon_models) - ydb_models)
    _log("=== Amazon 差分 (型番ベース) ===")
    _log(f"  ヨドバシ在庫あり 型番数: {len(ydb_models)}")
    _log(f"  Amazon 中間スプシ 型番数: {len(amazon_models)}")
    _log(f"  ★ ヨドバシのみ (Amazon 未収集): {len(only_ydb)}")
    _log(f"  両方に存在: {len(both)}")
    _log(f"  Amazon のみ (ヨドバシ在庫なし/未収集): {len(only_amz)}")
    if only_ydb:
        _log("  --- ヨドバシのみ 型番 (先頭30) ---")
        for m in only_ydb[:30]:
            _log(f"    {m}")

    # スプシ append
    sheet_result = None
    if args.dry_run:
        _log("[SKIP] スプシ append skip (= --dry-run)")
    elif not kept:
        _log("[SKIP] スプシ append skip (= keep 0 件)")
    else:
        from sheet_writer_yodobashi import append_yodobashi_items  # noqa: PLC0415
        items = [{
            "url": p["url"], "title": p["title"],
            "price_jpy": p["price_jpy"], "model_number": p["model_number"],
        } for p in kept]
        sheet_result = append_yodobashi_items(items, label=args.label)
        _log(f"[SHEET] {sheet_result}")

    _log("=== summary ===")
    _log(json.dumps({
        "collected": len(products), "kept": len(kept), "reject": rej,
        "diff": {"only_yodobashi": len(only_ydb), "both": len(both),
                 "only_amazon": len(only_amz)},
        "sheet": sheet_result, "dump": str(dump_path),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
