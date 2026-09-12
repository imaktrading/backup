# -*- coding: utf-8 -*-
"""VMAX / ex / V / VSTAR / GX などの **空のレアリティ** を公式から取り直して埋める (2026-09-13).

HQ 依頼 `requests/2026-09-11_pokemon_vmax_rarity_rrr_missing.md`。
公式ページに `ic_rare_rrr.gif` が在るのに `specs.rarity` が空。VMAX 143行だけでなく、
同じ形が ex 228 / V 176 / EX 174 / GX 74 / VSTAR 52 / V-UNION 5 = **合計852行** あった。

原因: 取り込みの parse は今も正しく RRR を取れる (実測)。**8/22 の取り直しが rarity を
書いていなかった**。= 「取り込んだ後の突合」では見えない穴 (依頼書の指摘どおり)。

やること: 852行の `source_url` (公式の詳細ページ) を1件ずつ取り直し、
`_parse_detail_html` が返した rarity で **空の行だけ** 埋める (在る値は触らない)。
生 HTML は倉庫へ。公式にもレアリティ表示が無い行 (プロモ / スターター) は空のまま。

★`rarity_ebay` は既存の変換表 (`ebay_filter_map`) に任せる。ここでは生値だけ入れる。

実行:
    python migrations/2026-09-13_pokemon_special_rarity_refetch.py --limit 20
    python migrations/2026-09-13_pokemon_special_rarity_refetch.py --commit
"""
from __future__ import annotations

import argparse
import json
import re
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
import pokemon_tcg as P  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/140.0 Safari/537.36"}
FAMILY = re.compile(r"(VMAX|VSTAR|V-UNION|GX|EX|ex|V)$")
PACE = 0.8


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    db = sqlite3.connect(str(api._DB_PATH), timeout=120)
    db.row_factory = sqlite3.Row
    rows = []
    for r in db.execute("SELECT id, product_id, name, specs, source_url FROM products "
                        "WHERE category='pokemon_tcg' AND source_url <> ''"):
        s = json.loads(r["specs"] or "{}")
        if not s.get("rarity") and FAMILY.search((r["name"] or "").strip()):
            rows.append((r, s))
    if a.limit:
        rows = rows[:a.limit]
    print(f"=== 空のレアリティを公式から ({'APPLY' if a.commit else 'DRY-RUN'}) — {len(rows)}行 ===",
          flush=True)
    now = datetime.now().isoformat(timespec="seconds")
    stat, n = Counter(), 0
    for i, (r, s) in enumerate(rows, 1):
        cid = (re.findall(r"/card/(\d+)", r["source_url"]) or [""])[0]
        try:
            with urllib.request.urlopen(urllib.request.Request(r["source_url"], headers=UA),
                                        timeout=40) as resp:
                h = resp.read().decode("utf-8", "ignore")
        except Exception as e:
            stat[f"取れない ({type(e).__name__})"] += 1
            time.sleep(PACE)
            continue
        _raw_store.save("pokemon_tcg", f"detail_{cid}", h, r["source_url"], ext="html")
        d = P._parse_detail_html(h, cid) or {}
        rar = d.get("rarity")
        if not rar:
            stat["公式にも表示が無い"] += 1
        else:
            stat[f"{rar} を入れた"] += 1
            s["rarity"] = rar
            s["rarity_source"] = "official_refetch_20260913"
            n += 1
            if a.commit:
                db.execute("UPDATE products SET specs=?, updated_at=? WHERE id=?",
                           (json.dumps(s, ensure_ascii=False), now, r["id"]))
                db.commit()                     # ★1行ごとに保存
        if i % 50 == 0:
            print(f"    {i}/{len(rows)} {dict(stat)}", flush=True)
        time.sleep(PACE)
    db.close()
    print("")
    for k, v in stat.most_common():
        print(f"  {k:24s} {v}")
    print(f"\n{'適用' if a.commit else '(dry-run — --commit で適用)'} {n}行")


if __name__ == "__main__":
    main()
