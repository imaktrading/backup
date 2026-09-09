# -*- coding: utf-8 -*-
"""UNIQLO UT の公式在庫と catalog を突き合わせる (2026-09-09 新設).

TCG の `official_drift_*.py` と同型。**公式を今その場で取り直す**。

## なぜ要るか

2026-05-05 に取り込んだきりで、**それ以降に出た商品が丸ごと抜けていた**。
2026-09-09 実測: 公式在庫 265件のうち **150件が catalog に無かった**
(ちいかわ / ポケモン / 集英社100周年マンガUT / SPY×FAMILY / BLEACH …)。
ユーザーが「公式在庫での出品物で見てみて」と言うまで誰も気づいていない。

**UT は廃盤になると公式から全部消える** (detail API も商品ページも 404)。
実寸表は復元手段が無い。だから「新商品を出たそばから取る」ことが要になる。

## 見るもの

    A. 公式在庫に在るのに catalog に無い          → 取り込み漏れ (新商品)
    B. catalog に在るが 出品に要る値が入っていない  → uniqlo_ut_enrich.py 未実行
    C. 実寸表がまだの現行品                      → uniqlo_ut_sizechart.py 未実行

★キッズ・ベビーは対象外 (2026-09-09 ユーザー確定)。

使い方:
    python tools/official_drift_uniqlo.py
"""
from __future__ import annotations

import json
import sqlite3
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import api  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

CATEGORY = "uniqlo_ut"
SEARCH = "https://www.uniqlo.com/jp/api/commerce/v5/ja/products?q=UT&limit=100&offset={off}"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/140.0 Safari/537.36"}
KID_GENDERS = {"KIDS", "BABY"}


def official_stock() -> list[dict]:
    """今 公式で買える UT 全部."""
    out, off = [], 0
    while True:
        with urllib.request.urlopen(
                urllib.request.Request(SEARCH.format(off=off), headers=UA), timeout=30) as r:
            d = json.loads(r.read().decode("utf-8", "ignore"))
        res = d.get("result") or {}
        items = res.get("items") or []
        out += items
        total = (res.get("pagination") or {}).get("total") or 0
        off += 100
        if off >= total or not items:
            break
    return out


def check() -> dict:
    stock = official_stock()
    db = sqlite3.connect(str(api._DB_PATH), timeout=120)
    try:
        rows = db.execute("SELECT product_id, specs FROM products WHERE category=?",
                          (CATEGORY,)).fetchall()
    finally:
        db.close()
    have, no_fields, no_chart = set(), 0, 0
    for pid, sp in rows:
        have.add(pid)
        s = json.loads(sp or "{}")
        if str(s.get("gender") or "").upper() in KID_GENDERS or s.get("official_gone_at"):
            continue
        if not s.get("enriched_at"):
            no_fields += 1
        elif not (s.get("size_chart") or s.get("size_chart_absent_at")):
            # ★`size_chart_absent_at` は「公式が寸法を消した」「衣類でない」と
            #   実測で確定した行。取りこぼしではないので数に入れない
            #   (2026-09-10: 23件を「まだ」と誤って出していた)
            no_chart += 1
    missing = [i for i in stock if i.get("productId") not in have]
    return {"stock": len(stock), "missing": missing,
            "no_fields": no_fields, "no_chart": no_chart}


def main() -> None:
    res = check()
    print(f"=== 公式在庫との突合 (uniqlo_ut) {datetime.now():%Y-%m-%d %H:%M} ===")
    print(f"  公式在庫 {res['stock']}件 / **catalog に無い {len(res['missing'])}件**")
    for i in res["missing"][:10]:
        print(f"      [欠落] {i.get('productId')} {(i.get('name') or '')[:40]}")
    print(f"  出品に要る値がまだ {res['no_fields']}件 (scrapers/uniqlo_ut_enrich.py)")
    print(f"  実寸表がまだ       {res['no_chart']}件 (scrapers/uniqlo_ut_sizechart.py)")
    sys.exit(0 if not res["missing"] else 1)


if __name__ == "__main__":
    main()
