# -*- coding: utf-8 -*-
"""UT のコラボ特設ページ (作品紹介文) を取り込む (2026-09-10 新設).

## なぜ要るか

商品APIには **作品の紹介文が無い**。それは各コラボの**特設ページ**にだけ在る:

    https://www.uniqlo.com/jp/ja/spl/ut-graphic-tees/one-piece-26ss/men
    og:description = 「原作は『週刊少年ジャンプ』(集英社刊) で1997年より連載中の
                     尾田栄一郎による少年漫画。テレビアニメは'99年よりスタートし…」

出品の Description には「About This Collaboration」の段落が要る (skill
`apparel-tee-listing`) が、今は毎回 AI が書いている。**公式の文が唯一の一次情報**。

**そして特設ページはコラボが終わると消える。**
実測 (2026-09-10): 2020年の鬼滅の刃の特設 `contents/feature/ut-kimetsu2020/anime.html` は
**もう別ページに飛ばされる**。商品ページより先に消える。

ユーザー指示 (2026-09-10):「google で ユニクロ 鬼滅の刃 の検索結果にある公式情報も取ってほしい。
むしろこちらの方が、勝ちがある」「鬼滅の刃以外もね」。

## 取り方 — **サイトマップから**。サイト内の一覧では足りない

    https://www.uniqlo.com/jp/sitemap_jp-ia_all.xml

★サイト内の「コレクションラインナップ」は **今やっているコラボ 42件だけ**。
  終わったコラボは導線から外れるが **ページは残っている**。
  ユーザー指摘 (2026-09-10):「ユニクロ公式で鬼滅の刃 UT を検索しても出てこない」。
  サイトマップには **spl 66スラッグ / カテゴリ 173スラッグ** が載っていて、
  鬼滅・ドラゴンボール・ガンダム45周年・ゴジラ70周年・FF・ダンダダン等の
  終わったコラボもここから辿れる。

    /jp/ja/spl/ut-graphic-tees/<slug>/<men|women|kids|baby>   コラボ特設 (紹介文が在る)
    /jp/ja/<gender>/tops/ut-graphic-tees/<slug>               カテゴリページ

各ページから取るもの:

    og:title        コラボ名 (`UTコレクション｜ONE PIECE｜MEN（メンズ）`)
    og:description  **作品紹介文** (これが本命)
    E4xxxxx-000     そのページに出ている商品番号 -> 行に紐付ける

★生の HTML は `_raw/uniqlo_ut/` に保管 (`collab_<slug>_<gender>`)。
  次に別の項目が要っても取り直さない。消えたら取り直せない。

## 途中保存 (CLAUDE.md「長く走るものは必ず途中保存」)

  - コラボ1つごとに保存 / 再実行は保管済みを飛ばす (飛ばした件数を出す)

実行:
    python scrapers/uniqlo_ut_collab.py             # 何件対象か見る
    python scrapers/uniqlo_ut_collab.py --commit
"""
from __future__ import annotations

import argparse
import json
import re
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

CATEGORY = "uniqlo_ut"
SITEMAP = "https://www.uniqlo.com/jp/sitemap_jp-ia_all.xml"
SPL = "https://www.uniqlo.com/jp/ja/spl/ut-graphic-tees/{slug}/{g}"
GENDERS = ("men", "women", "kids", "baby")
UA = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/140.0 Safari/537.36"),
      "Accept-Language": "ja,en;q=0.8"}
SLEEP = 0.5
STORE = Path("C:/dev/iMak_data/catalog/_ut_collabs.json")
_PID = re.compile(r"E\d{6}-\d{3}")


def _get(url: str) -> str:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        return r.read().decode("utf-8", "ignore")


def _meta(html: str, name: str) -> str:
    m = re.search(rf'<meta[^>]+(?:name|property)="{re.escape(name)}"[^>]+content="([^"]*)"',
                  html)
    return m.group(1).strip() if m else ""


def collab_urls() -> list[str]:
    """**サイトマップ**から UT のコラボ関連 URL を全部取る (終わったコラボも入る)."""
    import gzip
    b = urllib.request.urlopen(
        urllib.request.Request(SITEMAP, headers=UA), timeout=90).read()
    if b[:2] == bytes([0x1F, 0x8B]):
        b = gzip.decompress(b)
    locs = re.findall(r"<loc>([^<]+)</loc>", b.decode("utf-8", "ignore"))
    spl = {u for u in locs if "/spl/ut-graphic-tees/" in u}
    # ★カテゴリページ (`/tops/ut-graphic-tees/<slug>`) の**中身は使わない**。
    #   説明が「ユニクロキッズのUTの商品一覧です」の定型で、商品も一覧の36件が出るだけ。
    #   ただし **slug は過去コラボの名前**なので、同じ slug の spl が在るか試す価値がある
    #   (`kimetsu-no-yaiba` はサイトマップの spl に無いが、spl として生きている)。
    cat_slugs = {m.group(1) for u in locs
                 if (m := re.search(r"/tops/ut-graphic-tees/([a-z0-9\-]+)", u))}
    for sl in cat_slugs:
        spl.add(SPL.format(slug=sl, g="men"))
    return sorted(spl)


def key_of(url: str) -> str:
    """保管キー (`spl_<slug>_<gender>` / `cat_<gender>_<slug>`)."""
    m = re.search(r"/spl/ut-graphic-tees/([a-z0-9\-]+)/(\w+)", url)
    if m:
        return f"spl_{m.group(1)}_{m.group(2)}"
    m = re.search(r"/(\w+)/tops/ut-graphic-tees/([a-z0-9\-]+)", url)
    if m:
        return f"cat_{m.group(1)}_{m.group(2)}"
    return "other_" + re.sub(r"\W+", "_", url)[-60:]


def parse(html: str) -> dict:
    """特設ページ -> {name, description, product_ids}."""
    title = _meta(html, "og:title")          # 'UTコレクション｜ONE PIECE｜MEN（メンズ）'
    name = ""
    parts = [p.strip() for p in re.split(r"[｜|]", title) if p.strip()]
    if len(parts) >= 2:
        name = parts[1]
    desc = _meta(html, "og:description") or _meta(html, "description")
    # 先頭の定型 (【ユニクロオンラインストア｜MEN UT】) は落とす
    desc = re.sub(r"^【[^】]*】", "", desc).strip()
    # ★定型文は紹介文ではない。2種類ある:
    #   1. カテゴリページ 「…のUTの商品一覧です。新作、値下げ中の…」
    #   2. **終わったコラボ** — URL は 200 を返すが中身が UT のトップ (ソフト404)。
    #      og:title が `UTコレクション TOP`、説明が「アート、マンガ、音楽、ゲーム…」になる。
    #      2026-09-10 実測: `kimetsu-no-yaiba` / `archive-onepiece` がこれ。
    #      = **紹介文は開催中しか取れない**。だから定期的に取り続けるしかない。
    if ("の商品一覧です" in desc
            or "世界中のポップカルチャーが集まる" in desc
            or title.startswith("UTコレクション TOP")):
        desc = ""
    return {"name": name, "description": desc,
            "product_ids": sorted(set(_PID.findall(html)))}


def run(commit: bool, limit: int | None) -> None:
    urls = collab_urls()
    print(f"  サイトマップの UT コラボ URL: {len(urls)}本")
    store = {}
    if STORE.exists():
        store = json.loads(STORE.read_text(encoding="utf-8"))
    todo = [u for u in urls if key_of(u) not in store]
    print(f"  取得済み {len(urls) - len(todo)}本 は飛ばす")
    if limit:
        todo = todo[:limit]
    print(f"=== UT コラボ特設 ({'APPLY' if commit else 'DRY-RUN'}) — 対象 {len(todo)}本 ===")

    now = datetime.now().isoformat(timespec="seconds")
    db = sqlite3.connect(str(api._DB_PATH), timeout=120)
    db.row_factory = sqlite3.Row
    stat, tagged, n = Counter(), 0, 0
    for url in todo:
        key = key_of(url)
        try:
            h = _get(url)
        except urllib.error.HTTPError as e:
            stat[f"HTTP {e.code}"] += 1
            time.sleep(SLEEP)
            continue
        except Exception as e:
            stat[type(e).__name__] += 1
            time.sleep(SLEEP)
            continue
        _raw_store.save(CATEGORY, key, h, url, ext="html")
        p = parse(h)
        if not p["description"]:
            stat["紹介文が無い"] += 1
            time.sleep(SLEEP)
            continue
        rec = {"key": key, "url": url, "fetched_at": now, **p}
        stat["取れた"] += 1
        print(f"    + {key:34s} {p['name'][:20]:22s} 商品 {len(p['product_ids']):3d}件"
              f"  {p['description'][:40]}", flush=True)
        time.sleep(SLEEP)
        if not commit:
            continue
        store[key] = rec
        STORE.parent.mkdir(parents=True, exist_ok=True)
        STORE.write_text(json.dumps(store, ensure_ascii=False, indent=1), encoding="utf-8")

        # そのページに出ていた商品行に紹介文を紐付ける
        for pid in p["product_ids"]:
            r = db.execute("SELECT id, specs FROM products WHERE category=? AND product_id=?",
                           (CATEGORY, pid)).fetchone()
            if not r:
                continue
            s = json.loads(r["specs"] or "{}")
            if s.get("collab_page_key") == key:
                continue
            s["collab_page_key"] = key
            s["collab_page_url"] = url
            s["collab_official_name"] = p["name"]
            s["collab_official_text"] = p["description"]
            db.execute("UPDATE products SET specs=?, updated_at=? WHERE id=?",
                       (json.dumps(s, ensure_ascii=False), now, r["id"]))
            tagged += 1
        n += 1
        db.commit()                          # ★1ページごとに保存
    db.close()
    print("")
    for k, v in stat.most_common():
        print(f"  {k:24s} {v}")
    print("")
    print(f"{'適用' if commit else '(dry-run — --commit で適用)'} "
          f"コラボ {len(store)}件 / 商品に紐付け {tagged}行")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    run(a.commit, a.limit)


if __name__ == "__main__":
    main()
