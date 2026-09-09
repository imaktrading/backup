# -*- coding: utf-8 -*-
"""GU のグラフィックT を catalog に取り込む (2026-09-09 新設).

## なぜ要るか

UT と同じ理由。**廃盤になると公式から全部消える。**
2026-09-09 実測: 出品に使っている仕入元 135件のうち **30件が GU** で、catalog は
UNIQLO の UT しか持っていなかった。GU も UT と同じで、消えたら実寸表は復元できない。
ユーザー確定 (2026-09-09):「入れて」。

## 公式は UNIQLO と同じ v5 API (ホストだけ違う)

    https://www.gu-global.com/jp/api/commerce/v5/ja/products?q=グラフィックT   … 在庫一覧 (84件)
    https://www.gu-global.com/jp/api/commerce/v5/ja/products/{pid}/price-groups/00/details

取れるものも同じ: 全画像 (chip/main/sub) / composition / countriesOfOrigin /
designDetail / longDescription / colors / sizes。

★実寸表だけは PDP のモーダルを開くしかない (UNIQLO と同じ)。列の並びが UNIQLO と違い
  **身丈 / 裄丈 / 肩幅 / 身幅** なので、`gu_sizechart` 側で並びを変えないこと
  (skill `apparel-tee-listing`)。

★キッズは対象外 (2026-09-09 ユーザー確定)。`KIDSグラフィックT` は入れない。

## 途中保存 (CLAUDE.md「長く走るものは必ず途中保存」)

  - 20件ごとに commit / 再実行は DB を見て済んだ分を飛ばす (飛ばした件数を出す)
  - 生の JSON は `_raw/gu/` に保管 (次に別の項目が要っても取り直さない)
  - 廃盤 (404) は `specs.official_gone_at` を残して二度と叩かない

実行:
    python scrapers/gu_graphic_tee.py                    # 何件対象か見る
    python scrapers/gu_graphic_tee.py --commit
    python scrapers/gu_graphic_tee.py --commit --ids E361356-001,E359492-000
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
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

CATEGORY = "gu"
SOURCE = "gu_official_api"
BASE = "https://www.gu-global.com/jp/api/commerce/v5/ja"
SEARCH = BASE + "/products?{q}"
DETAIL = BASE + "/products/{pid}/price-groups/00/details?includeModelSize=true&httpFailure=true"
PDP = "https://www.gu-global.com/jp/ja/products/{pid}/00"
UA = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/140.0 Safari/537.36"),
      "Accept-Language": "ja,en;q=0.8"}
SLEEP = 0.4
SAVE_EVERY = 20
# ★UT と同じく一番大きい絵を採る (`?impolicy=quality` で 2100x2800)
BIG = "?impolicy=quality"
QUERIES = ("グラフィックT", "グラフィックスウェット")


def _get(url: str) -> str:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        return r.read().decode("utf-8", "ignore")


def discover() -> list[dict]:
    """今 公式で買えるグラフィックT。キッズは落とす."""
    out, seen = [], set()
    for q in QUERIES:
        off = 0
        while True:
            u = SEARCH.format(q=urllib.parse.urlencode(
                {"q": q, "limit": 100, "offset": off}))
            res = (json.loads(_get(u)).get("result") or {})
            items = res.get("items") or []
            for i in items:
                pid = i.get("productId")
                nm = i.get("name") or ""
                if not pid or pid in seen or nm.startswith("KIDS"):
                    continue
                seen.add(pid)
                out.append(i)
            total = (res.get("pagination") or {}).get("total") or 0
            off += 100
            if off >= total or not items:
                break
            time.sleep(SLEEP)
    return out


def big(u: str) -> str:
    if not u or "?" in u or "/chip/" in u:
        return u
    return u + BIG


def all_images(images: dict) -> list[str]:
    """main -> sub -> features -> chip の順で1本に (UNIQLO と同じ)."""
    out: list[str] = []

    def add(u):
        u = big(u)
        if u and u not in out:
            out.append(u)

    for _k, v in sorted((images.get("main") or {}).items()):
        add(v.get("image") if isinstance(v, dict) else v)
    for v in images.get("sub") or []:
        add(v.get("image") if isinstance(v, dict) else v)
    for v in images.get("features") or []:
        add(v.get("imageUrl") if isinstance(v, dict) else v)
    for _k, v in sorted((images.get("chip") or {}).items()):
        add(v if isinstance(v, str) else (v or {}).get("image"))
    return out


def build(pid: str, d: dict, listed: dict | None) -> dict:
    """公式の値だけで1行を組む。推測しない."""
    specs = {
        "brand": "GU",
        "gender": d.get("genderName") or (listed or {}).get("genderName") or "",
        "gender_category": d.get("genderCategory") or "",
        "colors_official": [c.get("name") for c in (d.get("colors") or []) if c.get("name")],
        "sizes_official": [s.get("name") for s in (d.get("sizes") or []) if s.get("name")],
        "composition": d.get("composition") or "",
        "countries_of_origin": [x.get("code") for x in (d.get("countriesOfOrigin") or [])
                                if x.get("code")],
        "design_detail": d.get("designDetail") or "",
        "long_description": d.get("longDescription") or "",
        "short_description": d.get("shortDescription") or "",
        "care_instruction": d.get("careInstruction") or "",
        "size_chart_url": d.get("sizeChartUrl") or "",
        "image_urls": all_images(d.get("images") or {}),
        "enriched_at": datetime.now().isoformat(timespec="seconds"),
    }
    if listed:
        pr = ((listed.get("prices") or {}).get("promo")
              or (listed.get("prices") or {}).get("base") or {})
        if pr.get("value"):
            specs["price_jpy"] = pr["value"]
    return {
        "category": CATEGORY, "product_id": pid,
        "name": d.get("name") or (listed or {}).get("name") or "",
        "name_jp": d.get("name") or "",
        "set_name": None, "set_name_official": None, "card_set_id": None,
        "language": "ja", "specs": specs,
        "images": specs["image_urls"],
        "source": SOURCE, "source_url": PDP.format(pid=pid),
    }


def run(commit: bool, ids: list[str] | None, limit: int | None) -> None:
    db = sqlite3.connect(str(api._DB_PATH), timeout=120)
    db.row_factory = sqlite3.Row
    done, gone = set(), set()
    for pid, sp in db.execute("SELECT product_id, specs FROM products WHERE category=?",
                              (CATEGORY,)):
        s = json.loads(sp or "{}")
        (done if s.get("enriched_at") else gone if s.get("official_gone_at") else set()).add(pid)
    db.close()

    if ids:
        listed = {}
        targets = [p for p in ids]
    else:
        items = discover()
        listed = {i.get("productId"): i for i in items}
        targets = list(listed)
        print(f"  公式在庫 (キッズ除く) {len(targets)}件")
    todo = [p for p in targets if p not in done and p not in gone]
    print(f"  済み {len(targets) - len(todo)}件 は飛ばす")
    if limit:
        todo = todo[:limit]
    print(f"=== GU 取り込み ({'APPLY' if commit else 'DRY-RUN'}) — 対象 {len(todo)}件 ===")

    stat, n = Counter(), 0
    for i, pid in enumerate(todo, 1):
        try:
            raw = _get(DETAIL.format(pid=pid))
        except urllib.error.HTTPError as e:
            stat[f"HTTP {e.code}" if e.code != 404 else "廃盤 (公式から消えた)"] += 1
            time.sleep(SLEEP)
            continue
        except Exception as e:
            stat[type(e).__name__] += 1
            time.sleep(SLEEP)
            continue
        _raw_store.save(CATEGORY, f"detail_{pid}", raw, DETAIL.format(pid=pid), ext="json")
        d = json.loads(raw).get("result") or {}
        rec = build(pid, d, listed.get(pid))
        stat["取れた"] += 1
        if rec["images"]:
            stat["画像あり"] += 1
        if commit:
            api.upsert(**rec)
            n += 1
            if n % SAVE_EVERY == 0:            # ★途中保存
                print(f"    ... {n}件 保存 ({i}/{len(todo)})", flush=True)
        time.sleep(SLEEP)

    for k, v in stat.most_common():
        print(f"  {k:24s} {v}")
    print("")
    print(f"{'適用' if commit else '(dry-run — --commit で適用)'} {n}件")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    ap.add_argument("--ids", help="品番をカンマ区切りで指定 (仕入元リストの救済用)")
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    run(a.commit, [x.strip() for x in a.ids.split(",")] if a.ids else None, a.limit)


if __name__ == "__main__":
    main()
