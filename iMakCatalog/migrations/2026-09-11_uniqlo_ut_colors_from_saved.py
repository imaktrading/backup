# -*- coding: utf-8 -*-
"""UT の色の一覧・サイズ・価格・eBay 固定値を、保存済みの公式 JSON から埋める (2026-09-11).

## なぜ要るか (Advisor 依頼 `requests/2026-09-11_ut_color_variants_missing.md`)

探索 (`uniqlo_ut_discover.py`) と廃盤の起こし (`uniqlo_ut_revive.py`) は、画像と説明文しか
書いていなかった。`color_variants` / `ebay_colors` が無く、出品側が色を選べずに止まった
(男性・男女兼用で 529件)。= **①カタログのデータの抜け** (取り込みの経路の不具合)。

## どこから埋めるか — 取り直さない

公式 detail の生 JSON (`_raw/uniqlo_ut/detail_<pid>.json.gz`) か、Wayback のページ
(`revive_<pid>.html.gz`、中に同じ形の product JSON) を読み、検索 API の取り込みと同じ
`uniqlo_ut.specs_from_detail()` を通す。**空いている項目だけ**埋める (在る値は触らない)。

あわせて:
- `composition` (素材) が空なら JSON の値で埋める
- 性別の書き方をそろえる: `男女兼用` → `UNISEX` (検索 API と detail API で書き方が違った。
  eBay の Department はどちらも `Unisex Adults` で変わらない)

実行:
    python migrations/2026-09-11_uniqlo_ut_colors_from_saved.py
    python migrations/2026-09-11_uniqlo_ut_colors_from_saved.py --commit
"""
from __future__ import annotations

import argparse
import gzip
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
import uniqlo_ut as U  # noqa: E402
import uniqlo_ut_revive as R  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

RAW = Path("C:/dev/iMak_data/catalog/_raw/uniqlo_ut")
EMPTY = (None, "", [], {})


def saved_product(pid: str) -> tuple[dict | None, str]:
    p = RAW / f"detail_{pid}.json.gz"
    if p.exists():
        j = json.loads(gzip.open(p, "rt", encoding="utf-8").read())
        return (j.get("result") or j), "detail"
    p = RAW / f"revive_{pid}.html.gz"
    if p.exists():
        h = gzip.open(p, "rb").read().decode("utf-8", "ignore")
        d = R._pdp_product(h, pid)
        if d:
            return d, "wayback"
    return None, ""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    a = ap.parse_args()

    db = sqlite3.connect(str(api._DB_PATH), timeout=120)
    db.row_factory = sqlite3.Row
    now = datetime.now().isoformat(timespec="seconds")
    stat, todo = Counter(), []
    for r in db.execute("SELECT id, product_id, specs FROM products WHERE category='uniqlo_ut'"):
        s = json.loads(r["specs"] or "{}")
        before = json.dumps(s, ensure_ascii=False, sort_keys=True)
        if s.get("gender") == "男女兼用":
            s["gender"] = "UNISEX"
            stat["性別をそろえた"] += 1
        if s.get("color_variants") and s.get("composition"):
            if json.dumps(s, ensure_ascii=False, sort_keys=True) != before:
                todo.append((r, s))
            continue
        d, where = saved_product(r["product_id"])
        if not d:
            stat["保存した JSON が無い"] += 1
            if json.dumps(s, ensure_ascii=False, sort_keys=True) != before:
                todo.append((r, s))
            continue
        base = U.specs_from_detail(d)
        filled = []
        for k, v in base.items():
            if k in ("gender", "collab", "image_urls"):
                continue                       # 起こした時の値 (大文字の性別・パンくずのコラボ名) を残す
            if s.get(k) in EMPTY and v not in EMPTY:
                s[k] = v
                filled.append(k)
        if s.get("composition") in EMPTY and d.get("composition"):
            s["composition"] = d["composition"]
            filled.append("composition")
        if "color_variants" in filled:
            stat[f"色を埋めた ({where})"] += 1
        elif not s.get("color_variants"):
            stat[f"JSON にも色が無い ({where})"] += 1
        if "composition" in filled:
            stat["素材を埋めた"] += 1
        if json.dumps(s, ensure_ascii=False, sort_keys=True) != before:
            todo.append((r, s))

    print(f"=== UT の色・サイズ・価格を保存済み JSON から ({'APPLY' if a.commit else 'DRY-RUN'}) ===")
    for k, v in stat.most_common():
        print(f"  {k:28s} {v}")
    if a.commit:
        for r, s in todo:
            db.execute("UPDATE products SET specs=?, updated_at=? WHERE id=?",
                       (json.dumps(s, ensure_ascii=False), now, r["id"]))
        db.commit()
    db.close()
    print(f"\n{'適用' if a.commit else '(dry-run — --commit で適用)'} {len(todo)}行")


if __name__ == "__main__":
    main()
