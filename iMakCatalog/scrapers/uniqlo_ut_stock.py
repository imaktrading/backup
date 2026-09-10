# -*- coding: utf-8 -*-
"""UT / GU の **在庫** を取る — 「もう公式で買えない」を見分けるため (2026-09-10 新設).

## なぜ要るか (ユーザー確定 2026-09-10)

> 「今買えないものをメルカリとかで新規未使用を仕入れて売るのがしたいから、
>   ものすごく重要なの」

無在庫の仕入れ元はメルカリ等。**公式で買えるものは商売にならない**ので、
仕入れて出す対象は「**公式では売り切れ / 廃盤だが、現物は流通している**」もの。
つまり catalog は **買えるか買えないかを持っていないと役に立たない**。

    E481120-000  鬼滅の刃 UT       在庫 0   -> 仕入れ対象
    E485482-000  (現行の UT)      在庫 88  -> 対象外 (公式で買える)

## どこから取るか

    .../products/{pid}/price-groups/00/l2s?withPrices=true&withStocks=true

`l2s` が 色×サイズ の一覧、`stocks` が l2Id ごとの数量。
サイズ名・色名は catalog が既に持っている `size_variants` / `color_variants` で引く。

## 入れる値

    in_stock          1つでも在庫があるか
    stock_total       全部の合計
    stock_by_size     {"M": 11, "L": 0, ...}   ★どのサイズが消えたかが分かる
    stock_by_color    {"OFF WHITE": 4, ...}
    stock_checked_at  見た日時
    sold_out_since    **初めて0を見た日**。以後 在庫が戻るまで書き換えない
                      (いつから買えないか = 仕入れの難易度の目安)

★在庫は動くので **毎回取り直す** (「済みは飛ばす」を適用しない項目)。
  ただし1件ごとに保存し、途中で落ちても次が続きから走る。

実行:
    python scrapers/uniqlo_ut_stock.py --limit 5
    python scrapers/uniqlo_ut_stock.py --commit
    python scrapers/uniqlo_ut_stock.py --brand gu --commit
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime
from pathlib import Path

_CATALOG_ROOT = Path(__file__).resolve().parent.parent
if str(_CATALOG_ROOT) not in sys.path:
    sys.path.insert(0, str(_CATALOG_ROOT))
import api  # noqa: E402
sys.path.insert(0, str(_CATALOG_ROOT / "scrapers"))
import _raw_store  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BRANDS = {
    "uniqlo": ("uniqlo_ut", "https://www.uniqlo.com/jp/api/commerce/v5/ja/products/"
                            "{pid}/price-groups/00/l2s"
                            "?withPrices=true&withStocks=true&httpFailure=true"),
    "gu": ("gu", "https://www.gu-global.com/jp/api/commerce/v5/ja/products/"
                 "{pid}/price-groups/00/l2s"
                 "?withPrices=true&withStocks=true&httpFailure=true"),
}
UA = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/140.0 Safari/537.36")}
KID = {"KIDS", "BABY"}
SLEEP = 0.5
CATEGORY, L2S = BRANDS["uniqlo"]


def _get(url: str, timeout: int = 30) -> str:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA),
                                timeout=timeout) as r:
        return r.read().decode("utf-8", "ignore")


def fetch(pid: str) -> dict | None:
    """色×サイズごとの在庫。**廃盤は 404**（= 公式から完全に消えた）."""
    raw = _get(L2S.format(pid=pid))
    _raw_store.save(CATEGORY, f"stock_{pid}", raw, L2S.format(pid=pid), ext="json")
    return json.loads(raw).get("result") or {}


def summarize(res: dict, specs: dict) -> dict:
    """l2s + stocks を 「サイズ別 / 色別」にまとめる."""
    size_name = {x.get("code"): x.get("name") for x in (specs.get("size_variants") or [])
                 if isinstance(x, dict)}
    color_name = {x.get("code"): x.get("name") for x in (specs.get("color_variants") or [])
                  if isinstance(x, dict)}
    stocks = res.get("stocks") or {}
    by_size: Counter = Counter()
    by_color: Counter = Counter()
    total = 0
    for l2 in (res.get("l2s") or []):
        st = stocks.get(l2.get("l2Id")) or {}
        q = st.get("quantity")
        if not isinstance(q, int):
            continue
        sc = (l2.get("size") or {}).get("code")
        cc = (l2.get("color") or {}).get("code")
        by_size[size_name.get(sc) or sc or "?"] += q
        by_color[color_name.get(cc) or cc or "?"] += q
        total += q
    return {"stock_total": total, "in_stock": total > 0,
            "stock_by_size": dict(by_size), "stock_by_color": dict(by_color)}


def targets(db, include_kids: bool) -> list[sqlite3.Row]:
    rows = db.execute("SELECT id, product_id, name, specs FROM products WHERE category=?",
                      (CATEGORY,)).fetchall()
    out, kids, notprod = [], 0, 0
    for r in rows:
        s = json.loads(r["specs"] or "{}")
        if not include_kids and str(s.get("gender") or "").upper() in KID:
            kids += 1
            continue
        if s.get("is_collab_overview"):
            notprod += 1
            continue
        out.append(r)
    print(f"  キッズ・ベビー {kids}行 は対象外 / 商品でない行 {notprod}行 は対象外")
    print("  ★在庫は動くので **毎回取り直す** (飛ばさない)")
    return out


def run(commit: bool, include_kids: bool, limit: int | None, brand: str) -> None:
    global CATEGORY, L2S
    CATEGORY, L2S = BRANDS[brand]
    db = sqlite3.connect(str(api._DB_PATH), timeout=120)
    db.row_factory = sqlite3.Row
    rows = targets(db, include_kids)
    if limit:
        rows = rows[:limit]
    print(f"=== {brand} 在庫 ({'APPLY' if commit else 'DRY-RUN'}) — 対象 {len(rows):,}行 ===",
          flush=True)

    now = datetime.now().isoformat(timespec="seconds")
    stat, n = Counter(), 0
    for i, r in enumerate(rows, 1):
        s = json.loads(r["specs"] or "{}")
        try:
            res = fetch(r["product_id"])
        except urllib.error.HTTPError as e:
            # 404 = 公式から消えた。**買えないことは確か**なので、その形で残す
            if e.code == 404:
                stat["公式から消えている"] += 1
                sm = {"stock_total": 0, "in_stock": False,
                      "stock_by_size": {}, "stock_by_color": {}}
            else:
                stat[f"HTTP {e.code}"] += 1
                time.sleep(SLEEP)
                continue
        except Exception as e:
            stat[type(e).__name__] += 1
            time.sleep(SLEEP)
            continue
        else:
            sm = summarize(res, s)
            stat["買える" if sm["in_stock"] else "売り切れ"] += 1

        s.update(sm)
        s["stock_checked_at"] = now
        if sm["in_stock"]:
            s.pop("sold_out_since", None)        # 復活したら消す
        else:
            s.setdefault("sold_out_since", now)  # ★初めて0を見た日を残す
        if commit:
            saved = False
            for _ in range(6):                   # ★DB が塞がっても走行を落とさない
                try:
                    db.execute("UPDATE products SET specs=?, updated_at=? WHERE id=?",
                               (json.dumps(s, ensure_ascii=False), now, r["id"]))
                    db.commit()                  # ★1件ごとに保存
                    saved = True
                    break
                except sqlite3.OperationalError as e:
                    if "locked" not in str(e):
                        raise
                    stat["DB が塞がって待った"] += 1
                    time.sleep(20)
            n += saved
            if not saved:
                stat["保存できなかった"] += 1
        if i % 200 == 0:
            print(f"    {i:,}/{len(rows):,} 済み / 売り切れ {stat['売り切れ']:,}",
                  flush=True)
        time.sleep(SLEEP)
    db.close()

    print("")
    for k, v in stat.most_common():
        print(f"  {k:24s} {v:,}")
    print("")
    print(f"{'適用' if commit else '(dry-run — --commit で適用)'} {n:,}行")
    buyable = stat["買える"]
    gone = stat["売り切れ"] + stat["公式から消えている"]
    if buyable or gone:
        print(f"  → 公式で買える {buyable:,}着 / **買えない {gone:,}着** "
              f"(= メルカリ等で探す対象)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    ap.add_argument("--include-kids", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--brand", choices=sorted(BRANDS), default="uniqlo")
    a = ap.parse_args()
    run(a.commit, a.include_kids, a.limit, a.brand)


if __name__ == "__main__":
    main()
