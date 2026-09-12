# -*- coding: utf-8 -*-
"""取り直しで入れた rarity に eBay 用の値 (`rarity_ebay`) を付ける (2026-09-13).

`2026-09-13_pokemon_special_rarity_refetch.py` で 126行に `RRR` を入れたが、
**変換 (`rarity` → `rarity_ebay`) をかけていなかった**。
回帰テスト `tests/test_rarity_sp_composite_20260818.py::test_no_row_left_unmapped` が
「生値が在るのに ebay 値が空」を 126行 検知した (= 検知の仕組みは効いている)。

変換は `api.derive_rarity_ebay()` (= `ebay_filter_map` の変換表) に任せる。**推測しない**。
表に無い生値は空欄のまま (fail-closed) にし、件数を出す。

実行:
    python migrations/2026-09-13_pokemon_rarity_ebay_for_refetched.py
    python migrations/2026-09-13_pokemon_rarity_ebay_for_refetched.py --commit
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

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

CATS = ("pokemon_tcg", "one_piece_tcg", "gundam_tcg", "dragonball_scg")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    a = ap.parse_args()
    db = sqlite3.connect(str(api._DB_PATH), timeout=120)
    db.row_factory = sqlite3.Row
    now = datetime.now().isoformat(timespec="seconds")
    stat, n = Counter(), 0
    for cat in CATS:
        for r in db.execute("SELECT id, product_id, specs FROM products WHERE category=?", (cat,)):
            s = json.loads(r["specs"] or "{}")
            if not s.get("rarity") or s.get("rarity_ebay"):
                continue
            val = api.derive_rarity_ebay(cat, s.get("rarity"))
            if not val:
                stat[f"{cat} 変換表に無い ({s.get('rarity')})"] += 1
                continue
            s["rarity_ebay"] = val
            stat[f"{cat} {s['rarity']} -> {val}"] += 1
            n += 1
            if a.commit:
                db.execute("UPDATE products SET specs=?, updated_at=? WHERE id=?",
                           (json.dumps(s, ensure_ascii=False), now, r["id"]))
    if a.commit:
        db.commit()
    db.close()
    print(f"=== rarity_ebay を付ける ({'APPLY' if a.commit else 'DRY-RUN'}) ===")
    for k, v in stat.most_common(20):
        print(f"  {k:40s} {v}")
    print(f"\n{'適用' if a.commit else '(dry-run — --commit で適用)'} {n}行")


if __name__ == "__main__":
    main()
