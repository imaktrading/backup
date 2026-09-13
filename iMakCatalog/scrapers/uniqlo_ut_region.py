# -*- coding: utf-8 -*-
"""UNIQLO の **海外の公式** からも UT を取る (2026-09-13 新設).

きっかけ: 出品くん依頼 `requests/2026-09-12_ut_not_in_catalog.md` の大半が
「韓国限定」「海外限定」で、日本の公式には無い商品だった。

2026-09-13 実測: **同じ品番で 各国の公式 API が引ける**。

    jp  /jp/api/commerce/v5/ja/products/<pid>/price-groups/00/details   200 鬼滅の刃 UT
    us  /us/api/commerce/v5/en/products/<pid>/...                        200 Demon Slayer ... UT Graphic T-Shirt
    kr  /kr/api/commerce/v5/ko/products/<pid>/...                        404 (その国に無い品番)

= 国ごとに「その国で売っている UT」が引ける。しかも **アメリカ版には公式の英語名がある**
  (これまで英語名は出品側で作っていた)。

## 何をするか

    --list   その国の検索 API で UT を一覧し、日本に無い品番を出す
    --enrich 日本に在る品番の **英語名** を米国版から取る (`specs.name_en_official_us`)

★日本の catalog の値は上書きしない。国ごとの値は別のキーに入れる
  (`region_us` / `region_kr`)。どの国の公式から取ったかが後で分かる形。

実行:
    python scrapers/uniqlo_ut_region.py --list us --commit
    python scrapers/uniqlo_ut_region.py --list kr --commit
    python scrapers/uniqlo_ut_region.py --enrich us --commit
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
import uniqlo_ut as U  # noqa: E402
import uniqlo_ut_enrich as E  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

CATEGORY = "uniqlo_ut"
REGION = {"us": ("us", "en"), "kr": ("kr", "ko"), "tw": ("tw", "zh"), "sg": ("sg", "en")}
SEARCH = ("https://www.uniqlo.com/{r}/api/commerce/v5/{lang}/products"
          "?q=UT&limit=100&offset={off}&httpFailure=true")
DETAIL = ("https://www.uniqlo.com/{r}/api/commerce/v5/{lang}/products/{pid}"
          "/price-groups/00/details?includeModelSize=true&httpFailure=true")
UA = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/140.0 Safari/537.36")}
PACE = 0.4


def _get(url: str, tries: int = 3) -> dict | None:
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
        except Exception:
            pass
        time.sleep(4 * (i + 1))
    return None


def list_region(reg: str, commit: bool) -> None:
    r, lang = REGION[reg]
    db = sqlite3.connect(str(api._DB_PATH), timeout=120)
    have = {x[0] for x in db.execute(
        "SELECT product_id FROM products WHERE category IN ('uniqlo_ut','gu')")}
    items, off = {}, 0
    while True:
        j = _get(SEARCH.format(r=r, lang=lang, off=off))
        got = ((j or {}).get("result") or {}).get("items") or []
        for it in got:
            items[it.get("productId")] = it
        total = (((j or {}).get("result") or {}).get("pagination") or {}).get("total", 0)
        print(f"    {len(items)}/{total}", flush=True)
        off += 100
        if off >= total or not got:
            break
        time.sleep(PACE)
    new = [p for p in items if p and p not in have]
    print(f"\n=== {reg} の UT {len(items)}件 / 日本の catalog に無い {len(new)}件 ===")
    out = Path(f"C:/dev/iMak_data/catalog/_ut_region_{reg}_new.txt")
    out.write_text("\n".join(sorted(new)), encoding="ascii")
    print(f"  → {out}")
    if not commit:
        db.close()
        return
    now = datetime.now().isoformat(timespec="seconds")
    stat = Counter()
    for pid in sorted(new):
        j = _get(DETAIL.format(r=r, lang=lang, pid=pid))
        d = ((j or {}).get("result") or {})
        if not d:
            stat["詳細が取れない"] += 1
            time.sleep(PACE)
            continue
        _raw_store.save(CATEGORY, f"detail_{reg}_{pid}", json.dumps(j, ensure_ascii=False),
                        DETAIL.format(r=r, lang=lang, pid=pid), ext="json")
        bc = d.get("breadcrumbs") or {}
        if (bc.get("category") or {}).get("name") != "ut graphic tees":
            stat["UT でない"] += 1
            time.sleep(PACE)
            continue
        gender = (d.get("genderName") or "").strip().upper()
        if gender in ("KIDS", "BABY"):
            stat["キッズ"] += 1
            time.sleep(PACE)
            continue
        specs = U.specs_from_detail(d)
        # ★画像は detail の images をそのまま展開する (main/sub/chip)。
        #   検索 API 用の拾い方だと main の1枚しか入らない (2026-09-13 実測: 1枚 vs 10枚)
        imgs = E.all_images(d.get("images") or {})
        if imgs:
            specs["image_urls"] = imgs
        specs.update({"region": reg, "region_only": True, "gender": gender,
                      "department": U._gender_to_dept(gender),
                      "collab": ((bc.get("subcategory") or {}).get("locale") or ""),
                      "enriched_at": now, "discovered_at": now})
        name = d.get("name") or pid
        api.upsert(category=CATEGORY, product_id=pid, name=name, name_jp=name,
                   set_name=None, set_name_official=None, card_set_id=None,
                   language=lang, specs=specs, images=specs.get("image_urls") or [],
                   source=f"uniqlo_official_{reg}",
                   source_url=f"https://www.uniqlo.com/{r}/{lang}/products/{pid}/00")
        stat["入れた"] += 1
        print(f"    + {pid}  {name[:50]}", flush=True)
        time.sleep(PACE)
    db.close()
    for k, v in stat.most_common():
        print(f"  {k:16s} {v}")


def enrich_en(commit: bool, limit: int | None) -> None:
    """日本に在る UT の **公式の英語名** を米国版から取る."""
    db = sqlite3.connect(str(api._DB_PATH), timeout=120)
    db.row_factory = sqlite3.Row
    rows = [r for r in db.execute(
        "SELECT id, product_id, specs FROM products WHERE category='uniqlo_ut'")
        if not json.loads(r["specs"] or "{}").get("name_en_official_us")
        and not json.loads(r["specs"] or "{}").get("not_tee")]
    if limit:
        rows = rows[:limit]
    print(f"=== 米国版から英語名 ({'APPLY' if commit else 'DRY-RUN'}) — {len(rows)}行 ===", flush=True)
    now = datetime.now().isoformat(timespec="seconds")
    stat, n = Counter(), 0
    for i, r in enumerate(rows, 1):
        j = _get(DETAIL.format(r="us", lang="en", pid=r["product_id"]))
        d = ((j or {}).get("result") or {})
        if not d.get("name"):
            stat["米国に無い"] += 1
        else:
            s = json.loads(r["specs"] or "{}")
            s["name_en_official_us"] = d["name"]
            s["name_en_source"] = "uniqlo_official_us_20260913"
            stat["英語名が取れた"] += 1
            n += 1
            if commit:
                db.execute("UPDATE products SET specs=?, updated_at=? WHERE id=?",
                           (json.dumps(s, ensure_ascii=False), now, r["id"]))
                db.commit()                     # ★1行ごとに保存
        if i % 100 == 0:
            print(f"    {i}/{len(rows)} {dict(stat)}", flush=True)
        time.sleep(PACE)
    db.close()
    for k, v in stat.most_common():
        print(f"  {k:16s} {v}")
    print(f"\n{'適用' if commit else '(dry-run)'} {n}行")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", choices=sorted(REGION))
    ap.add_argument("--enrich", choices=["us"])
    ap.add_argument("--commit", action="store_true")
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    if a.list:
        list_region(a.list, a.commit)
    elif a.enrich:
        enrich_en(a.commit, a.limit)


if __name__ == "__main__":
    main()
