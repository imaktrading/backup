#!/usr/bin/env python3
"""products.specs.set_name_ebay を変換表から引き直す (焼き直し).

決定: hq/requests/2026-08-21_set_name_and_name_en_need_ebay_facet_response.md (窓口 Advisor)
      「手で置き換えるのではなく set_name_official から引き直す。適用前に dry-run で止める」

## なにをするか
`derive_set_name_ebay(category, set_name_official, product_id)` を全行で引き直し、
stored と違う行を新しい値に揃える。**手で値を書かない**。

  - derived が None の行は触らない (fail-closed。空欄のまま)
  - stored == derived の行は触らない
  - category を指定しなければ pokemon_tcg のみ (他は凍結)

## なぜ必要か
変換表を直しても products に焼いてある値は古いまま残る (契約 v1.2 §1-5 の restamp 方式)。
2026-08-21 に変換表を eBay の新マスタ (Game 別) へ合わせたので、その分を反映する。

実行:
  python tools/restamp_set_name_ebay.py                    # dry-run (既定)
  python tools/restamp_set_name_ebay.py --commit
  python tools/restamp_set_name_ebay.py --category all     # 全カテゴリ
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

NOW = datetime.now().isoformat()
SOURCE = "restamp_from_filter_map_20260821"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    ap.add_argument("--category", default="pokemon_tcg",
                    help="'all' で全カテゴリ (既定: pokemon_tcg のみ。他は凍結)")
    args = ap.parse_args()

    db = sqlite3.connect(api._DB_PATH)
    db.row_factory = sqlite3.Row
    if args.category == "all":
        rows = db.execute("SELECT id, category, product_id, set_name_official, specs FROM products "
                          "WHERE set_name_official IS NOT NULL")
    else:
        rows = db.execute("SELECT id, category, product_id, set_name_official, specs FROM products "
                          "WHERE category=? AND set_name_official IS NOT NULL", (args.category,))

    pairs, updates, skipped_none = Counter(), [], 0
    for r in rows:
        s = json.loads(r["specs"] or "{}")
        stored = s.get("set_name_ebay") or ""
        derived = api.derive_set_name_ebay(r["category"], r["set_name_official"], r["product_id"])
        if derived is None:
            skipped_none += 1
            continue
        if derived == stored:
            continue
        pairs[(stored or "(空)", derived)] += 1
        s["set_name_ebay"] = derived
        s["set_name_ebay_source"] = SOURCE
        updates.append((json.dumps(s, ensure_ascii=False), NOW, r["id"]))

    print("=== set_name_ebay 焼き直し (%s / category=%s) ==="
          % ("APPLY" if args.commit else "DRY-RUN", args.category))
    print("変わる行 %d / %d 組   (derived が空で触らなかった行 %d)\n"
          % (len(updates), len(pairs), skipped_none))
    print("%-40s %-42s %s" % ("今の値", "引き直した値", "行数"))
    for (st, de), n in pairs.most_common(40):
        print("%-40s %-42s %d" % (st[:39], de[:41], n))
    if len(pairs) > 40:
        print("... 他 %d 組" % (len(pairs) - 40))

    if args.commit and updates:
        db.executemany("UPDATE products SET specs=?, updated_at=? WHERE id=?", updates)
        db.commit()
        print("\n[OK] 適用 %d 行" % len(updates))
    elif not args.commit:
        print("\n(dry-run — --commit で適用)")
    db.close()


if __name__ == "__main__":
    main()
