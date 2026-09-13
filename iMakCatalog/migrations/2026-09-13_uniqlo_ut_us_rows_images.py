# -*- coding: utf-8 -*-
"""米国の公式から入れた UT の画像を全部入れ直す (2026-09-13).

`scrapers/uniqlo_ut_region.py --list us --commit` の初回は、検索 API 用の拾い方で
**main の1枚しか**入れていなかった (実測: DB 1枚 / API から 10枚)。
detail の images (main/sub/chip) を展開して入れ直す。

実行:
    python migrations/2026-09-13_uniqlo_ut_us_rows_images.py
    python migrations/2026-09-13_uniqlo_ut_us_rows_images.py --commit
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
import urllib.request
from collections import Counter
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
import api  # noqa: E402
sys.path.insert(0, str(_ROOT / "scrapers"))
import _raw_store  # noqa: E402
import uniqlo_ut_enrich as E  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

DETAIL = ("https://www.uniqlo.com/us/api/commerce/v5/en/products/{pid}"
          "/price-groups/00/details?includeModelSize=true&httpFailure=true")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/140.0 Safari/537.36"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    a = ap.parse_args()
    db = sqlite3.connect(str(api._DB_PATH), timeout=120)
    db.row_factory = sqlite3.Row
    rows = db.execute("SELECT id, product_id, specs FROM products "
                      "WHERE source='uniqlo_official_us'").fetchall()
    print(f"=== 米国行の画像を入れ直す ({'APPLY' if a.commit else 'DRY-RUN'}) — {len(rows)}行 ===")
    now = datetime.now().isoformat(timespec="seconds")
    stat, n = Counter(), 0
    for r in rows:
        url = DETAIL.format(pid=r["product_id"])
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as resp:
                raw = resp.read().decode("utf-8", "ignore")
        except Exception as e:
            stat[f"取れない ({type(e).__name__})"] += 1
            continue
        _raw_store.save("uniqlo_ut", f"detail_us_{r['product_id']}", raw, url, ext="json")
        d = (json.loads(raw).get("result") or {})
        imgs = E.all_images(d.get("images") or {})
        s = json.loads(r["specs"] or "{}")
        before = len(s.get("image_urls") or [])
        if len(imgs) <= before:
            stat["増えない"] += 1
            continue
        s["image_urls"] = imgs
        stat[f"{before} -> {len(imgs)}枚"] += 1
        n += 1
        if a.commit:
            db.execute("UPDATE products SET specs=?, images=?, updated_at=? WHERE id=?",
                       (json.dumps(s, ensure_ascii=False), json.dumps(imgs, ensure_ascii=False),
                        now, r["id"]))
            db.commit()
        time.sleep(0.4)
    db.close()
    for k, v in stat.most_common(10):
        print(f"  {k:20s} {v}")
    print(f"\n{'適用' if a.commit else '(dry-run — --commit で適用)'} {n}行")


if __name__ == "__main__":
    main()
