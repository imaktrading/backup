# -*- coding: utf-8 -*-
"""廃盤で素材などが空の UT を、Wayback のページから埋める (2026-09-11).

Advisor 依頼 `requests/2026-09-11_ut_color_variants_missing.md` Q4: 素材 (`composition`) が無い
男性・男女兼用 Tシャツ 27件。実測で **27件とも廃盤 (official_gone_at あり) で、
仕上げ (enrich) 前に公式から消え、Wayback のページも取っていなかった**。

`uniqlo_ut_revive.from_wayback` (新しい保存から読む) でページを取り、倉庫に保存してから、
空いている項目だけを埋める (在る値は触らない)。

実行:
    python migrations/2026-09-11_uniqlo_ut_fill_gone_from_wayback.py
    python migrations/2026-09-11_uniqlo_ut_fill_gone_from_wayback.py --commit
"""
from __future__ import annotations

import argparse
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
import _raw_store  # noqa: E402
import uniqlo_ut as U  # noqa: E402
import uniqlo_ut_revive as R  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

EMPTY = (None, "", [], {})
KEYS = {"composition": "composition", "design_detail": "designDetail",
        "long_description": "longDescription", "short_description": "shortDescription",
        "care_instruction": "careInstruction"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    a = ap.parse_args()
    db = sqlite3.connect(str(api._DB_PATH), timeout=120)
    db.row_factory = sqlite3.Row
    rows = [r for r in db.execute(
        "SELECT id, product_id, specs FROM products WHERE category='uniqlo_ut'")
        if (lambda s: s.get("official_gone_at") and not s.get("composition")
            and not s.get("not_tee")
            and str(s.get("gender") or "").upper() not in ("KIDS", "BABY"))(
                json.loads(r["specs"] or "{}"))]
    print(f"=== 廃盤で素材が空の UT を Wayback から ({'APPLY' if a.commit else 'DRY-RUN'}) "
          f"— 対象 {len(rows)}件 ===", flush=True)
    now = datetime.now().isoformat(timespec="seconds")
    stat = Counter()
    for r in rows:
        pid = r["product_id"]
        d, h = R.from_wayback(pid)
        if not d:
            stat["Wayback にも中身が無い"] += 1
            continue
        s = json.loads(r["specs"] or "{}")
        filled = [k for k, src in KEYS.items() if s.get(k) in EMPTY and d.get(src)]
        for k in filled:
            s[k] = d[KEYS[k]]
        for k, v in U.specs_from_detail(d).items():
            if k not in ("gender", "collab", "image_urls") and s.get(k) in EMPTY and v not in EMPTY:
                s[k] = v
        stat["素材を埋めた" if "composition" in filled else "素材は Wayback にも無い"] += 1
        print(f"    {pid}  {', '.join(filled) or '-'}", flush=True)
        if a.commit:
            _raw_store.save("uniqlo_ut", f"revive_{pid}", h, R.PDP.format(pid=pid), ext="html")
            db.execute("UPDATE products SET specs=?, updated_at=? WHERE id=?",
                       (json.dumps(s, ensure_ascii=False), now, r["id"]))
            db.commit()
    db.close()
    print("")
    for k, v in stat.most_common():
        print(f"  {k:24s} {v}")


if __name__ == "__main__":
    main()
