#!/usr/bin/env python3
"""ワンピの Leader が持っている `cost` は **ライフ**。名前を直す (503行).

2026-08-22。HQ 指摘。公式 API が Leader に返す `Cost/Life` の数字は**ライフ**で、
コストではない。公式の Leader にコストは無い。

  実測: /api/user/card/66038 (OP06-022 Yamato)
        Card Type=Leader / Cost/Life=4 / Power=5000   ← この 4 はライフ

旧 migration (2026-05-30_opcg_field_normalize) が `Cost/Life -> cost` と一律に
寄せていた (コメントに「leader Life ≈ cost 同等」と書いてある)。
出品くんが「読むだけ」になると **公式に無いコストがそのまま出品に出る**ので直す。

  Leader の行: cost の値を life に移し、cost は消す
  Leader 以外: 触らない (cost のままで正しい)

実行:
  python migrations/2026-08-22_opcg_leader_life_not_cost.py           # dry-run
  python migrations/2026-08-22_opcg_leader_life_not_cost.py --commit
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import api  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

NOW = datetime.now().isoformat(timespec="seconds")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()
    db = sqlite3.connect(api._DB_PATH)
    db.row_factory = sqlite3.Row
    n, updates, ex = Counter(), [], []
    for r in db.execute("SELECT id, product_id, specs FROM products WHERE category='one_piece_tcg'"):
        s = json.loads(r["specs"] or "{}")
        if "LEADER" not in str(s.get("card_type") or "").upper():
            continue
        n["Leader"] += 1
        v = str(s.get("cost") or "").strip()
        if not v:
            continue
        if not str(s.get("life") or "").strip():
            s["life"] = v
            n["life に移した"] += 1
        s.pop("cost", None)
        s["leader_cost_fix"] = "2026-08-22_life_not_cost"
        n["cost を消した"] += 1
        if len(ex) < 4:
            ex.append(f"{r['product_id']}: cost={v} -> life={v}")
        updates.append((json.dumps(s, ensure_ascii=False), NOW, r["id"]))

    print("=== ワンピ Leader の cost -> life (%s) ===" % ("APPLY" if args.commit else "DRY-RUN"))
    print("  ", dict(n))
    for e in ex:
        print("   ", e)
    if args.commit and updates:
        db.executemany("UPDATE products SET specs=?, updated_at=? WHERE id=?", updates)
        db.commit()
        print("[OK] 適用 %d 行" % len(updates))
    elif not args.commit:
        print("(dry-run — --commit で適用)")
    db.close()


if __name__ == "__main__":
    main()
