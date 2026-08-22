#!/usr/bin/env python3
"""card_type_ebay の取りこぼしを埋める (eBay の一覧に在る値だけ).

2026-08-22。HQ から「`card_type` は 36,199行あるのに `card_type_ebay` は 42%」と指摘。
調べたところ、埋められるのは **ポケモンの 'Pokémon' / 'Trainer' だけ**だった。

残りは eBay の Card Type 一覧 (74値) に無い = 天井:
  ワンピ  Character / Event / Leader / DON!! Card / Stage
  DBSCG   BATTLE / EXTRA / LEADER / ENERGY MARKER
  ガンダム UNIT / PILOT / COMMAND / BASE
これらは寄せずに空欄のままにする (近い値に寄せない)。
ポケモンの 'Energy' 40行も、eBay は 'Energy-Basic' / 'Energy-Special' の2値しか持たず
どちらか決められないので空欄のまま。

実行:
  python migrations/2026-08-22_card_type_ebay_fill.py           # dry-run
  python migrations/2026-08-22_card_type_ebay_fill.py --commit
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
MASTER = Path(r"C:\dev\iMak_data\catalog\_input\ebay_aspects_183454_latest.json")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()
    CT = set(json.loads(MASTER.read_text(encoding="utf-8"))["aspects"]["Card Type"]["all"])
    db = sqlite3.connect(api._DB_PATH)
    db.row_factory = sqlite3.Row
    n, skip, updates = Counter(), Counter(), []
    for r in db.execute("SELECT id, category, specs FROM products WHERE category IN "
                        "('pokemon_tcg','one_piece_tcg','dragonball_scg','gundam_tcg')"):
        s = json.loads(r["specs"] or "{}")
        if str(s.get("card_type_ebay") or "").strip():
            continue
        raw = str(s.get("card_type") or "").strip()
        if not raw:
            skip["生も空"] += 1
            continue
        if raw in CT:                      # 完全一致だけ。寄せない
            s["card_type_ebay"] = raw
            s["card_type_ebay_source"] = "exact_match_20260822"
            n[f"{r['category']}:{raw}"] += 1
            updates.append((json.dumps(s, ensure_ascii=False), NOW, r["id"]))
        else:
            skip[f"eBay に無い: {raw}"] += 1
    print("=== card_type_ebay 補完 (%s) ===" % ("APPLY" if args.commit else "DRY-RUN"))
    print("  埋める %d 行: %s" % (len(updates), dict(n)))
    print("  見送り 上位: %s" % skip.most_common(6))
    if args.commit and updates:
        db.executemany("UPDATE products SET specs=?, updated_at=? WHERE id=?", updates)
        db.commit()
        print("[OK] 適用 %d 行" % len(updates))
    elif not args.commit:
        print("(dry-run — --commit で適用)")
    db.close()


if __name__ == "__main__":
    main()
