"""compare_mercari_api_vs_chrome - メルカリ検索を Chrome版/API版で同じキーワードで
回し、拾う URL を突き合わせる (2026-10-01 HQ依頼 `2026-10-01_harvest_api_parallel_build.md`).

**既存の収集スクリプト (run_harvest_mercari_*.py) は一切触らない・呼ばない。**
ここで Chrome版 (`scrapers/mercari_search.collect_search_listing_urls`) と
API版 (`scrapers/mercari_search_api.collect_multi_keyword_urls_api`) を直接呼んで
比べるだけの、独立した検証ツール。 本番の切替はしない (結果を見てユーザーが go するまで)。

使い方:
  python tools/compare_mercari_api_vs_chrome.py                       # 既定10語 (chara_market.csv先頭)
  python tools/compare_mercari_api_vs_chrome.py --keywords "PSA10 ピカチュウ" "PSA10 カビゴン"
  python tools/compare_mercari_api_vs_chrome.py --n 20 --cap 30
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

OUT_DIR = ROOT / "debug"


def _log(m: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def _default_keywords(n: int) -> list[str]:
    """既定のキーワード = chara_market.csv の先頭 n 件 (無ければ demand_market.csv)."""
    from scrapers import chara_keywords  # noqa: PLC0415

    rows = chara_keywords.load_rows()
    if rows:
        return chara_keywords.build_keywords(rows)[:n]
    from scrapers import treasure_keywords  # noqa: PLC0415
    rows = treasure_keywords.load_rows()
    return treasure_keywords.build_keywords(rows)[:n]


def run_chrome(keywords: list[str], cap: int, price_min, price_max) -> dict:
    from scrapers import mercari_seller as MS  # noqa: PLC0415
    from scrapers import mercari_search as MSch  # noqa: PLC0415
    from scrapers._chrome_util import kill_chrome_for_profile, kill_orphan_chromedriver  # noqa: PLC0415

    kill_chrome_for_profile(MS.CHROME_PROFILE_DIR_ANON)
    kill_orphan_chromedriver()
    driver = MS.create_anonymous_driver(headless=True)
    by_kw: dict[str, list[str]] = {}
    try:
        for i, kw in enumerate(keywords, 1):
            r = MSch.collect_search_listing_urls(kw, driver, price_min=price_min, price_max=price_max,
                                                 cap=cap)
            by_kw[kw] = r["urls"]
            _log(f"  [Chrome] {i}/{len(keywords)} {kw!r}: {len(r['urls'])}件")
            time.sleep(1.0)
    finally:
        try:
            driver.quit()
        except Exception:  # noqa: BLE001
            pass
        kill_chrome_for_profile(MS.CHROME_PROFILE_DIR_ANON)
        kill_orphan_chromedriver()
    return by_kw


def run_api(keywords: list[str], cap: int, price_min, price_max) -> dict:
    from scrapers.mercari_search_api import ApiSearchClient  # noqa: PLC0415

    cli = ApiSearchClient()
    by_kw: dict[str, list[str]] = {}
    try:
        for i, kw in enumerate(keywords, 1):
            r = cli.search_keyword(kw, price_min=price_min, price_max=price_max, cap=cap)
            by_kw[kw] = r["urls"]
            tag = f" ⚠{r['error']}" if r.get("error") else ""
            _log(f"  [API]    {i}/{len(keywords)} {kw!r}: {len(r['urls'])}件{tag}")
    finally:
        cli.close()
    return by_kw


def compare(chrome_by_kw: dict, api_by_kw: dict) -> dict:
    """純関数: キーワードごとの一致率・片方だけの件数をまとめる。"""
    rows = []
    for kw in chrome_by_kw:
        c = set(chrome_by_kw.get(kw) or [])
        a = set(api_by_kw.get(kw) or [])
        both = c & a
        rate = (len(both) / len(c)) if c else None
        rows.append({
            "keyword": kw, "chrome": len(c), "api": len(a), "both": len(both),
            "chrome_only": len(c - a), "api_only": len(a - c),
            "match_rate_of_chrome": round(rate, 3) if rate is not None else None,
        })
    total_c = sum(r["chrome"] for r in rows)
    total_both = sum(r["both"] for r in rows)
    overall_rate = round(total_both / total_c, 3) if total_c else None
    return {"rows": rows, "overall_match_rate_of_chrome": overall_rate,
            "total_chrome": total_c, "total_both": total_both}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keywords", nargs="*", default=None, help="比べるキーワード (既定=台帳から自動)")
    ap.add_argument("--n", type=int, default=10, help="既定キーワードを使う時の件数")
    ap.add_argument("--cap", type=int, default=30)
    ap.add_argument("--price-min", type=int, default=3000)
    ap.add_argument("--price-max", type=int, default=70000)
    args = ap.parse_args(argv)

    keywords = args.keywords or _default_keywords(args.n)
    if not keywords:
        _log("比べるキーワードが無い (台帳が空) → 終了")
        return 0
    _log(f"比較: {len(keywords)} 語 / cap={args.cap}")

    _log("=== Chrome版 ===")
    chrome_by_kw = run_chrome(keywords, args.cap, args.price_min, args.price_max)
    _log("=== API版 ===")
    api_by_kw = run_api(keywords, args.cap, args.price_min, args.price_max)

    result = compare(chrome_by_kw, api_by_kw)
    _log("=== 結果 ===")
    for r in result["rows"]:
        _log(f"  {r['keyword']!r}: Chrome={r['chrome']} API={r['api']} "
             f"両方={r['both']} Chromeのみ={r['chrome_only']} APIのみ={r['api_only']} "
             f"一致率(対Chrome)={r['match_rate_of_chrome']}")
    _log(f"全体一致率 (対Chrome): {result['overall_match_rate_of_chrome']} "
         f"({result['total_both']}/{result['total_chrome']})")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"compare_mercari_api_vs_chrome_{datetime.now():%Y%m%dT%H%M%S}.json"
    out_path.write_text(json.dumps({
        "keywords": keywords, "cap": args.cap,
        "chrome_by_keyword": {k: v for k, v in chrome_by_kw.items()},
        "api_by_keyword": {k: v for k, v in api_by_kw.items()},
        "compare": result,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    _log(f"[FILE] {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
