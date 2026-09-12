# -*- coding: utf-8 -*-
"""Fashion Press の **写真1枚ごとの説明文** を取る (2026-09-13 新設・ユーザー指示「取れるだけ取れ」).

記事本文の写真には説明文が付いているが、写真一覧 (Photos(37) の方) には付いていない。
一覧の各写真には専用ページ `/news/gallery/<記事ID>/<写真ID>` があり、そこの og:description に
「メンズ Tシャツ 1,990円 ※背面」のような説明文が入っている (2026-09-13 実測)。

= 公式から消えた昔のコラボでも、**どの柄が メンズ/ウィメンズ/キッズ で いくらだったか** が分かる。

## 取り方 / 保存

  - 写真ページの URL は **倉庫にある記事 HTML から拾う** (記事は取り直さない)
  - 1ページずつ取り、生 HTML を倉庫へ (`gallery_<記事ID>_<写真ID>`)。説明文は記事 JSON の
    `photo_captions` に入れる (URL → 説明文)
  - **済みは飛ばす** (倉庫にページが在れば取りに行かない)。20枚ごとに JSON を保存

実行:
    python scrapers/fashion_press_gallery.py --limit 2    # 動作確認
    python scrapers/fashion_press_gallery.py              # UT の記事ぶん全部
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import gzip
import html as htmllib
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scrapers"))
import _raw_store  # noqa: E402
import fashion_press_uniqlo as F  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

RAW = Path("C:/dev/iMak_data/catalog/_raw/fashion_press")
BASE = "https://www.fashion-press.net"
PACE = 1.2          # 連投すると弾かれる (2026-09-13 実測)


def gallery_links(nid: str) -> list[str]:
    """倉庫の記事 HTML から写真ページの URL を拾う."""
    p = RAW / f"news_{nid}.html.gz"
    if not p.exists():
        return []
    h = gzip.open(p, "rb").read().decode("utf-8", "ignore")
    return sorted(set(re.findall(rf"/news/gallery/{nid}/(\d+)", h)))


def fetch(job: tuple[str, str]) -> tuple[str, str, str, str]:
    """(記事ID, 写真ID, 画像URL, 説明文)."""
    nid, gid = job
    key = f"gallery_{nid}_{gid}"
    url = f"{BASE}/news/gallery/{nid}/{gid}"
    if _raw_store.have(F.RAW_CAT, key):
        h = gzip.open(RAW / f"{key}.html.gz", "rb").read().decode("utf-8", "ignore")
    else:
        # ★1回で諦めない (2026-09-13: 5,580枚中 3,892枚を取り逃がした。連投で弾かれる)
        h = ""
        for i in range(4):
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers=F.UA),
                                            timeout=40) as r:
                    h = r.read().decode("utf-8", "ignore")
                break
            except Exception:
                time.sleep(10 * (i + 1))
        if not h:
            return nid, gid, "", ""
        _raw_store.save(F.RAW_CAT, key, h, url, ext="html")       # ★取った時点で倉庫へ
        time.sleep(PACE)
    img = (re.findall(r'property="og:image" content="([^"?]+)', h) or [""])[0]
    cap = (re.findall(r'property="og:description" content="([^"]*)', h) or [""])[0]
    cap = htmllib.unescape(cap).split(" | ")[0].strip()
    return nid, gid, img, cap


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="UT 以外の記事も")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--workers", type=int, default=3)
    a = ap.parse_args()
    db = json.loads(F.OUT.read_text(encoding="utf-8"))
    arts = [x for x in db["articles"].values()
            if a.all or F.is_ut_article(x.get("title") or "", x.get("detail_text") or "")]
    arts.sort(key=lambda x: x.get("published") or "", reverse=True)
    if a.limit:
        arts = arts[:a.limit]
    jobs = [(x["id"], g) for x in arts for g in gallery_links(x["id"])
            if (x.get("photo_captions") or {}).get(g) is None]
    print(f"=== 写真1枚ごとの説明文 — 記事 {len(arts)}本 / 取る写真 {len(jobs):,}枚 ===", flush=True)
    by_id = {x["id"]: x for x in arts}
    got = 0
    with cf.ThreadPoolExecutor(max_workers=a.workers) as ex:
        for i, (nid, gid, img, cap) in enumerate(ex.map(fetch, jobs), 1):
            if cap:
                by_id[nid].setdefault("photo_captions", {})[gid] = {"img": img, "caption": cap}
                got += 1
            if i % 200 == 0:                      # ★途中保存
                F.OUT.write_text(json.dumps(db, ensure_ascii=False, indent=1), encoding="utf-8")
                print(f"    {i:,}/{len(jobs):,} 説明文 {got:,}", flush=True)
    F.OUT.write_text(json.dumps(db, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n  説明文が取れた {got:,}枚")


if __name__ == "__main__":
    main()
