# -*- coding: utf-8 -*-
"""Fashion Press の UT 記事の写真を **倉庫に保存する** (2026-09-11 新設・ユーザー指示).

## なぜ要るか

公式から取れない UT (2020年以前のコラボ等) は、何の柄だったかを示す画像が
Fashion Press の記事にしか残っていない。ユーザー指示:
「例外は、ファッションプレスで画像データを拡充させよう」
「ファッションプレスも同じように取り直さなくて済むよう倉庫化ね」

記事の HTML は `fashion_press_uniqlo.py` が `_raw/fashion_press/` に保存済み。
ここでは **写真の実物**を `_raw/fashion_press/img/<記事ID>/` に保存する。

## 何を保存するか

  - 本文の写真 (説明文つき。例「メンズ Tシャツ 1,990円 ※背面」) と、写真一覧の全部
  - 大きい形 (`w300_` を外した URL)。一覧用の小さい形は保存しない

## 途中保存 / 済みは飛ばす

  - 1枚ずつ保存。**ファイルが在る写真は取らない** (倉庫 = iMak_data にあるので機械が
    変わっても消えない)。飛ばした枚数を出す
  - 記事 JSON に `images_local` (URL → 倉庫のパス) を書き足す。20記事ごとに保存

実行:
    python scrapers/fashion_press_images.py --limit 2     # 動作確認
    python scrapers/fashion_press_images.py               # UT の記事の写真を全部
    python scrapers/fashion_press_images.py --all         # UT 以外の記事も
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

SRC = Path("C:/dev/iMak_data/catalog/fashion_press/uniqlo_articles.json")
IMG = Path("C:/dev/iMak_data/catalog/_raw/fashion_press/img")
UA = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/140.0 Safari/537.36"),
      "Referer": "https://www.fashion-press.net/"}
PACE = 0.4


def local_path(nid: str, url: str) -> Path:
    return IMG / nid / url.rsplit("/", 1)[-1].split("?")[0]


def fetch(job: tuple[str, str]) -> tuple[str, str, str]:
    """(記事ID, URL, 結果)。結果は 'ok' / 'skip' / 'gone' / 'err'."""
    nid, url = job
    p = local_path(nid, url)
    if p.exists() and p.stat().st_size > 0:
        return nid, url, "skip"
    for i in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
                data = r.read()
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(p.suffix + ".tmp")
            tmp.write_bytes(data)
            tmp.replace(p)
            time.sleep(PACE)
            return nid, url, "ok"
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return nid, url, "gone"
        except Exception:
            pass
        time.sleep(5 * (i + 1))
    return nid, url, "err"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="UT 以外の記事も")
    ap.add_argument("--limit", type=int, help="記事の数を絞る (動作確認用)")
    ap.add_argument("--workers", type=int, default=3)
    a = ap.parse_args()

    db = json.loads(SRC.read_text(encoding="utf-8"))
    arts = [x for x in db["articles"].values() if a.all or x.get("is_ut")]
    arts.sort(key=lambda x: x.get("published") or "", reverse=True)
    if a.limit:
        arts = arts[:a.limit]
    jobs = []
    for x in arts:
        urls = [f["url"] for f in x.get("figures") or []] + list(x.get("photos") or [])
        for u in dict.fromkeys(urls):
            jobs.append((x["id"], u))
    have = sum(1 for nid, u in jobs if local_path(nid, u).exists())
    print(f"=== Fashion Press の写真を倉庫へ — 記事 {len(arts)}件 / 写真 {len(jobs):,}枚 "
          f"(保存済み {have:,}枚 は飛ばす) ===", flush=True)
    stat: dict[str, int] = {}
    by_id = {x["id"]: x for x in arts}
    with cf.ThreadPoolExecutor(max_workers=a.workers) as ex:
        for i, (nid, url, res) in enumerate(ex.map(fetch, jobs), 1):
            stat[res] = stat.get(res, 0) + 1
            if res in ("ok", "skip"):
                by_id[nid].setdefault("images_local", {})[url] = str(local_path(nid, url))
            if i % 300 == 0:                    # ★途中保存
                SRC.write_text(json.dumps(db, ensure_ascii=False, indent=1), encoding="utf-8")
                print(f"    {i:,}/{len(jobs):,}  {stat}", flush=True)
    SRC.write_text(json.dumps(db, ensure_ascii=False, indent=1), encoding="utf-8")
    size = sum(f.stat().st_size for f in IMG.rglob("*") if f.is_file()) / 1e6
    print(f"\n  {stat}\n  倉庫: {IMG}  ({size:,.0f} MB)")


if __name__ == "__main__":
    main()
