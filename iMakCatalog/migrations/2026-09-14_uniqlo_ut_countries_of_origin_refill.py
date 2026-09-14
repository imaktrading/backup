"""UT の原産国 (countries_of_origin) の取りこぼしを埋める — 2026-09-14

依頼: requests/2026-09-13_ut_country_of_origin_coverage.md (出品くん)

実測 (2026-09-14):
    公式由来 (uniqlo_official_api / _sweep) で原産国が空 384行
        → 今 details を叩くと 351行が 200 で原産国あり (33行は公式から消えた)
        → 空だった理由: `uniqlo_ut_enrich.py` が **enriched_at が在る行を飛ばす**。
          見つけた時点 (discover / sweep) で enriched_at が付き、原産国を入れないまま「済み」になった
    Wayback 由来 (uniqlo_revive_wayback_*) で空 402行
        → 保存済みの商品ページの JSON に原産国あり 202行
          (revive が色やサイズを入れる経路で原産国を移していなかった)

取り方 (上から当たったもの。どれも公式の値):
    1. 手元の Wayback 保存 (`_raw/uniqlo_ut/revive_<pid>.html.gz`) の商品 JSON
    2. 手元の details (`detail_<pid>.json.gz`)
    3. 今の公式 details API (取った JSON は倉庫に残す)
どれにも無ければ空欄のまま (推測で埋めない)。

途中保存: 1行ごとに commit。再実行は原産国が空の行だけを見る。

実行:
    python migrations/2026-09-14_uniqlo_ut_countries_of_origin_refill.py            # dry-run
    python migrations/2026-09-14_uniqlo_ut_countries_of_origin_refill.py --commit
"""
from __future__ import annotations

import argparse
import gzip
import json
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "scrapers")]
import api  # noqa: E402
import _raw_store  # noqa: E402
import uniqlo_ut_revive as R  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

CATEGORY = "uniqlo_ut"
RAW = _raw_store.RAW_ROOT / CATEGORY
DETAIL = "https://www.uniqlo.com/jp/api/commerce/v5/ja/products/{pid}/price-groups/00/details"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/140.0 Safari/537.36"}


def _codes(d: dict | None) -> list[str]:
    return [x.get("code") for x in ((d or {}).get("countriesOfOrigin") or []) if x.get("code")]


def from_wayback(pid: str) -> list[str]:
    p = RAW / f"revive_{pid}.html.gz"
    if not p.exists():
        return []
    try:
        return _codes(R._pdp_product(gzip.open(p, "rt", encoding="utf-8", errors="ignore").read(), pid))
    except Exception:
        return []


def from_saved_detail(pid: str) -> list[str]:
    t = _raw_store.load(CATEGORY, f"detail_{pid}", ext="json")
    if not t:
        return []
    try:
        j = json.loads(t)
    except ValueError:
        return []
    return _codes(j.get("result") if isinstance(j.get("result"), dict) else j)


def from_live(pid: str) -> list[str]:
    url = DETAIL.format(pid=pid)
    try:
        raw = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30)\
            .read().decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError):
        return []
    try:
        j = json.loads(raw)
    except ValueError:
        return []
    if j.get("status") != "ok":
        return []
    _raw_store.save(CATEGORY, f"detail_{pid}", raw, url, ext="json")   # 取れたものは残す
    return _codes(j.get("result"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()

    db = sqlite3.connect(api._DB_PATH, timeout=120)
    rows = db.execute("SELECT id, product_id, source, specs FROM products "
                      "WHERE category=? AND product_id LIKE 'E%'", (CATEGORY,)).fetchall()
    stat = Counter()
    now = datetime.now().isoformat(timespec="seconds")
    for rid, pid, src, sp in rows:
        s = json.loads(sp or "{}")
        if s.get("data_level") == "fp_design" or s.get("not_tee"):
            continue
        if s.get("countries_of_origin"):
            stat["済み (飛ばす)"] += 1
            continue
        coo, how = from_wayback(pid), "wayback_saved"
        if not coo:
            coo, how = from_saved_detail(pid), "official_api_saved"
        if not coo and not s.get("region_only"):
            coo, how = from_live(pid), f"official_api_{now[:10]}"
            time.sleep(0.4)
        if not coo:
            stat["公式に値が無い (空欄のまま)"] += 1
            continue
        stat[f"入れた: {how.split('_20')[0]}"] += 1
        if args.commit:
            s["countries_of_origin"] = coo
            s["countries_of_origin_source"] = how
            db.execute("UPDATE products SET specs=?, updated_at=? WHERE id=?",
                       (json.dumps(s, ensure_ascii=False), now, rid))
            db.commit()                                   # ★1行ごとに保存
    for k, v in stat.most_common():
        print(f"  {k}: {v}")
    print("commit" if args.commit else "dry-run (書き込みなし)")


if __name__ == "__main__":
    main()
