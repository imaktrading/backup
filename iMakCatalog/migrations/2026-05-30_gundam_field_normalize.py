"""Gundam specs field 名 重複正規化 (= OPCG と同 pattern).

mapping (= Bandai 既存 大文字始 → 小文字 snake_case):
  Card Type        → card_type
  Color            → color
  Cost             → cost
  Rarity           → rarity
  AP               → ap
  HP               → hp
  Lv. (Level)      → level
  AP Boost         → ap_boost
  HP Boost         → hp_boost
  Trait            → trait
  Source Title     → source_title
  Link Requirement → link_requirement
  Zone             → zone
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import api  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

DB_PATH = str(api._DB_PATH)
NOW = datetime.now().isoformat()

MAPPING = {
    "Card Type": "card_type",
    "Color": "color",
    "Cost": "cost",
    "Rarity": "rarity",
    "AP": "ap",
    "HP": "hp",
    "Lv. (Level)": "level",
    "AP Boost": "ap_boost",
    "HP Boost": "hp_boost",
    "Trait": "trait",
    "Source Title": "source_title",
    "Link Requirement": "link_requirement",
    "Zone": "zone",
}


def normalize(specs: dict) -> tuple[dict, int]:
    out = dict(specs)
    deleted = 0
    for old, new in MAPPING.items():
        if old not in out:
            continue
        v = out.pop(old)
        deleted += 1
        if new not in out or out[new] in (None, "", []):
            if v not in (None, "", []):
                out[new] = v
    return out, deleted


def process(dry_run: bool):
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    rs = db.execute("SELECT id, specs FROM products WHERE category='gundam_tcg'").fetchall()
    affected = 0
    deleted_total = 0
    for r in rs:
        if not r["specs"]:
            continue
        try:
            s = json.loads(r["specs"])
        except Exception:
            continue
        new_s, d = normalize(s)
        if d == 0:
            continue
        affected += 1
        deleted_total += d
        if not dry_run:
            db.execute(
                "UPDATE products SET specs=?, updated_at=? WHERE id=?",
                (json.dumps(new_s, ensure_ascii=False), NOW, r["id"]),
            )
    if not dry_run:
        db.commit()
    db.close()
    print(f"total: {len(rs)}")
    print(f"affected: {affected}")
    print(f"deleted big keys: {deleted_total}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--probe", action="store_true")
    args = p.parse_args()
    print(f"=== Gundam field normalize ({'DRY-RUN' if args.probe else 'APPLY'}) ===")
    process(dry_run=args.probe)


if __name__ == "__main__":
    main()
