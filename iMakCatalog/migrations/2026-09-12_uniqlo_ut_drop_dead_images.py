# -*- coding: utf-8 -*-
"""起こした UT の **死んでいる画像URL** を外し、生きている画像を探し直す (2026-09-12).

Wayback のページに載っていた画像URLが、CDN では 404 のことがある
(2026-09-12 実測: 縮小版を保存しようとして 890枚が 404。ほとんどが起こした行)。
catalog が死んだ URL を持っていると、出品の画像も目視も壊れる。

やること (画像を持つ行すべて):
  1. 画像URLを **並行で HEAD** して生死を見る
  2. 死んだ URL を外す
  3. 1枚も残らなければ `uniqlo_ut_revive.images_of()` で総当たりして入れ直す
  4. それでも 0枚なら画像なしのまま (印は付けない。次回また探す)

実行:
    python migrations/2026-09-12_uniqlo_ut_drop_dead_images.py
    python migrations/2026-09-12_uniqlo_ut_drop_dead_images.py --commit
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
import api  # noqa: E402
sys.path.insert(0, str(_ROOT / "scrapers"))
import uniqlo_ut_revive as R  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    db = sqlite3.connect(str(api._DB_PATH), timeout=120)
    db.row_factory = sqlite3.Row
    rows = [r for r in db.execute(
        "SELECT id, product_id, specs, images FROM products "
        "WHERE category IN ('uniqlo_ut','gu')")
        if json.loads(r["specs"] or "{}").get("image_urls")]
    if a.limit:
        rows = rows[:a.limit]
    print(f"=== 死んだ画像URLを外す ({'APPLY' if a.commit else 'DRY-RUN'}) — {len(rows):,}行 ===",
          flush=True)
    now = datetime.now().isoformat(timespec="seconds")
    stat, n = Counter(), 0
    for k, r in enumerate(rows, 1):
        s = json.loads(r["specs"] or "{}")
        urls = s.get("image_urls") or []
        with cf.ThreadPoolExecutor(max_workers=16) as ex:
            alive = [u for u, ok in zip(urls, ex.map(R._head_ok, urls)) if ok]
        dead = len(urls) - len(alive)
        if not dead:
            stat["全部生きている"] += 1
            continue
        stat["死んだURLを外した"] += 1
        stat["外した枚数"] += dead
        if not alive:
            alive = R.images_of(r["product_id"])
            stat["探し直して入れ直した" if alive else "画像が1枚も無くなった"] += 1
        s["image_urls"] = alive
        s["images_checked_at"] = now
        if a.commit:
            db.execute("UPDATE products SET specs=?, images=?, updated_at=? WHERE id=?",
                       (json.dumps(s, ensure_ascii=False), json.dumps(alive, ensure_ascii=False),
                        now, r["id"]))
            db.commit()                        # ★1行ごとに保存
            n += 1
        if k % 200 == 0:
            print(f"    {k:,}/{len(rows):,} {dict(stat)}", flush=True)
    db.close()
    print("")
    for kk, v in stat.most_common():
        print(f"  {kk:24s} {v:,}")
    print(f"\n{'適用' if a.commit else '(dry-run — --commit で適用)'} {n:,}行")


if __name__ == "__main__":
    main()
