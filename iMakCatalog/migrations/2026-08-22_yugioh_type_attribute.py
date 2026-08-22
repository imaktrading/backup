#!/usr/bin/env python3
"""遊戯王の 種族 → Creature/Monster Type、属性 → Attribute を埋める.

2026-08-22。枠を作ったら Creature/Monster Type が 0% だった。
**ポケモンのタイプ (炎・水…) の置き場所はここではない** (eBay のこの項目は
Warrior / Dragon / Spellcaster 等の遊戯王・MTG 系の種族一覧)。ポケモンのタイプは
`Attribute/MTG:Color` の方に Fire / Water / Grass … が在る。

遊戯王は元データを既に持っている:
  - `race`      = 種族 (Warrior / Machine / Fiend …) → Creature/Monster Type
  - `attribute` = 属性 (DARK / LIGHT / EARTH …)      → Attribute/MTG:Color

## 守ること
- **eBay の一覧に完全一致する値だけ**入れる。近い値に寄せない。
  (`Creator God` は eBay の一覧に無いので入れない = 1行)
- 種族はモンスターだけ。魔法・罠の `race` は 'Continuous' 等の**発動形式**であって
  種族ではないので入れない。
- 既に値がある行は触らない。

実行:
  python migrations/2026-08-22_yugioh_type_attribute.py           # dry-run
  python migrations/2026-08-22_yugioh_type_attribute.py --commit
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
SOURCE = "yugioh_race_attribute_20260822"
MASTER = Path(r"C:\dev\iMak_data\catalog\_input\ebay_aspects_183454_latest.json")


def is_monster(s: dict) -> bool:
    ft = (s.get("frameType") or "").lower()
    ct = str(s.get("card_type") or s.get("type") or "").lower()
    return s.get("atk") is not None or "monster" in ct or (ft and ft not in ("spell", "trap"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()

    a = json.loads(MASTER.read_text(encoding="utf-8"))["aspects"]
    CT, AT = set(a["Creature/Monster Type"]["all"]), set(a["Attribute/MTG:Color"]["all"])
    db = sqlite3.connect(api._DB_PATH)
    db.row_factory = sqlite3.Row
    n_ct, n_at, skipped, updates = Counter(), Counter(), Counter(), []

    for r in db.execute("SELECT id, specs FROM products WHERE category='yugioh_tcg'"):
        s = json.loads(r["specs"] or "{}")
        touched = False
        if not (s.get("creature_type_ebay") or "").strip() and is_monster(s):
            race = (s.get("race") or "").strip()
            if race:
                if race in CT:
                    s["creature_type_ebay"] = race
                    n_ct[race] += 1
                    touched = True
                else:
                    skipped[f"race:{race}"] += 1
        if not (s.get("color_ebay") or "").strip():
            att = (s.get("attribute") or "").strip()
            if att:
                cand = att.capitalize()
                if cand in AT:
                    s["color_ebay"] = cand
                    n_at[cand] += 1
                    touched = True
                else:
                    skipped[f"attribute:{att}"] += 1
        if touched:
            s["aspect_fill_source_2"] = SOURCE
            updates.append((json.dumps(s, ensure_ascii=False), NOW, r["id"]))

    print("=== 遊戯王 種族/属性 (%s) ===" % ("APPLY" if args.commit else "DRY-RUN"))
    print("触る行 %d\n" % len(updates))
    print("  Creature/Monster Type +%d  上位: %s" % (sum(n_ct.values()), n_ct.most_common(6)))
    print("  Attribute            +%d  内訳: %s" % (sum(n_at.values()), n_at.most_common(10)))
    if skipped:
        print("  eBay の一覧に無いので見送り: %s" % skipped.most_common(5))

    if args.commit and updates:
        db.executemany("UPDATE products SET specs=?, updated_at=? WHERE id=?", updates)
        db.commit()
        print("\n[OK] 適用 %d 行" % len(updates))
    elif not args.commit:
        print("\n(dry-run — --commit で適用)")
    db.close()


if __name__ == "__main__":
    main()
