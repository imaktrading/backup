# -*- coding: utf-8 -*-
"""終わった UT コラボの特設ページを **Wayback から** 取り戻す (2026-09-10 新設).

## なぜ要るか

コラボが終わると、特設ページは **200 を返すのに中身が UT のトップ**になる (ソフト404)。
2026-09-10 実測: `kimetsu-no-yaiba` / `archive-onepiece` がそれ。
= **こちらが取りに行く前に終わったコラボの紹介文は、公式からはもう取れない。**

ユーザー指摘 (2026-09-10):「ユニクロ公式で鬼滅の刃 UT を検索しても出てこない」
「保存したらいいのでは？PSAのように」「じゃ、GOOGLEでやれば？」

→ Google は検索結果のリンクを返すだけで、消えたページの中身は取れない。
   **Wayback (web.archive.org) には当時の HTML がそのまま残っている。**

    CDX に `uniqlo.com/jp/ja/spl/ut-graphic-tees*` を問うと **413スラッグ**
    (公式サイトマップの66件の6倍以上)。`anime-demon-slayer-21fw` (鬼滅) /
    `attack-on-titan` / `bleach-23ss` / `blue-lock` / `ai-yazawa` … が読める。

## 取り方

    1. CDX でスナップショット一覧を取る (slug ごとに **一番新しい1本**だけ)
    2. `https://web.archive.org/web/<timestamp>id_/<url>` で当時の HTML を取る
       (`id_` = アーカイブのツールバーを挟まない生の形)
    3. `uniqlo_ut_collab.parse()` で 紹介文 / 商品番号 を抜く (現行と同じ読み方)
    4. 生 HTML は `_raw/uniqlo_ut/` に `wb_<slug>_<gender>` で保管

★Wayback は 429 (混みすぎ) を返すことがある。**待って続ける**。走行ごと落とさない。
★現行ページで既に取れている slug は飛ばす (公式の今の値が優先)。

## 途中保存 (CLAUDE.md「長く走るものは必ず途中保存」)

  - 1ページごとに保存 / 再実行は取得済みを飛ばす (飛ばした件数を出す)

実行:
    python scrapers/uniqlo_ut_collab_archive.py --limit 5
    python scrapers/uniqlo_ut_collab_archive.py --commit
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
import uniqlo_ut_collab as C  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

CATEGORY = "uniqlo_ut"
CDX = ("http://web.archive.org/cdx/search/cdx?url=uniqlo.com/jp/ja/spl/ut-graphic-tees*"
       "&output=json&fl=original,timestamp,statuscode&filter=statuscode:200"
       "&collapse=urlkey&limit=6000")
SNAP = "https://web.archive.org/web/{ts}id_/{url}"
UA = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/140.0 Safari/537.36")}
SLEEP = 2.0                                  # Wayback は混む。ゆっくり
STORE = Path("C:/dev/iMak_data/catalog/_ut_collabs_archive.json")
_SLUG = re.compile(r"/spl/ut-graphic-tees/([a-z0-9\-]+)/(\w+)")


def _get(url: str, tries: int = 4) -> str:
    """429 は待って何度か試す。駄目なら例外 (呼び出し側で次へ進む)."""
    for i in range(tries):
        try:
            with urllib.request.urlopen(
                    urllib.request.Request(url, headers=UA), timeout=60) as r:
                return r.read().decode("utf-8", "ignore")
        except urllib.error.HTTPError as e:
            if e.code in (429, 503) and i < tries - 1:
                time.sleep(20 * (i + 1))
                continue
            raise
    raise RuntimeError("unreachable")


def snapshots() -> dict[tuple[str, str], tuple[str, str]]:
    """{(slug, gender): (url, timestamp)} — slug/性別ごとに **一番新しい1本**."""
    rows = json.loads(_get(CDX))[1:]
    best: dict[tuple[str, str], tuple[str, str]] = {}
    for original, ts, *_ in rows:
        m = _SLUG.search(original)
        if not m:
            continue
        k = (m.group(1), m.group(2))
        if k not in best or ts > best[k][1]:
            best[k] = (original, ts)
    return best


def run(commit: bool, limit: int | None) -> None:
    snaps = snapshots()
    print(f"  Wayback のスナップショット: {len(snaps)}本 "
          f"({len({s for s, _ in snaps})}スラッグ)")

    store = json.loads(STORE.read_text(encoding="utf-8")) if STORE.exists() else {}
    live = {}
    if C.STORE.exists():
        live = json.loads(C.STORE.read_text(encoding="utf-8"))
    live_slugs = {k.split("_", 1)[1].rsplit("_", 1)[0] for k in live if k.startswith("spl_")}

    todo = [(k, v) for k, v in sorted(snaps.items())
            if f"wb_{k[0]}_{k[1]}" not in store and k[0] not in live_slugs]
    print(f"  取得済み・現行で取れている {len(snaps) - len(todo)}本 は飛ばす")
    if limit:
        todo = todo[:limit]
    print(f"=== 過去コラボ (Wayback) ({'APPLY' if commit else 'DRY-RUN'}) — "
          f"対象 {len(todo)}本 ===")

    now = datetime.now().isoformat(timespec="seconds")
    db = sqlite3.connect(str(api._DB_PATH), timeout=120)
    db.row_factory = sqlite3.Row
    stat, tagged = Counter(), 0
    for (slug, gender), (url, ts) in todo:
        key = f"wb_{slug}_{gender}"
        try:
            h = _get(SNAP.format(ts=ts, url=url))
        except Exception as e:
            stat[getattr(e, "code", None) and f"HTTP {e.code}" or type(e).__name__] += 1
            time.sleep(SLEEP)
            continue
        _raw_store.save(CATEGORY, key, h, SNAP.format(ts=ts, url=url), ext="html")
        p = C.parse(h)
        if not p["description"]:
            stat["紹介文が無い"] += 1
            time.sleep(SLEEP)
            continue
        stat["取れた"] += 1
        print(f"    + {slug:34s} {ts[:8]}  {p['name'][:16]:18s} "
              f"商品 {len(p['product_ids']):3d}件  {p['description'][:38]}", flush=True)
        time.sleep(SLEEP)
        if not commit:
            continue
        store[key] = {"key": key, "slug": slug, "gender": gender, "snapshot": ts,
                      "url": url, "fetched_at": now, **p}
        STORE.parent.mkdir(parents=True, exist_ok=True)
        STORE.write_text(json.dumps(store, ensure_ascii=False, indent=1), encoding="utf-8")

        for pid in p["product_ids"]:
            r = db.execute("SELECT id, specs FROM products WHERE category=? AND product_id=?",
                           (CATEGORY, pid)).fetchone()
            if not r:
                continue
            s = json.loads(r["specs"] or "{}")
            if s.get("collab_official_text"):        # 現行から取れた値を上書きしない
                continue
            s["collab_page_key"] = key
            s["collab_page_url"] = SNAP.format(ts=ts, url=url)
            s["collab_official_name"] = p["name"]
            s["collab_official_text"] = p["description"]
            s["collab_source"] = "wayback"
            db.execute("UPDATE products SET specs=?, updated_at=? WHERE id=?",
                       (json.dumps(s, ensure_ascii=False), now, r["id"]))
            tagged += 1
        db.commit()                          # ★1ページごとに保存
    db.close()
    print("")
    for k, v in stat.most_common():
        print(f"  {k:24s} {v}")
    print("")
    print(f"{'適用' if commit else '(dry-run — --commit で適用)'} "
          f"過去コラボ {len(store)}件 / 商品に紐付け {tagged}行")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    run(a.commit, a.limit)


if __name__ == "__main__":
    main()
