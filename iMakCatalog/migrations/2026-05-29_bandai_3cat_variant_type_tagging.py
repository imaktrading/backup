"""Bandai 3 cat (OPCG / Gundam / DBFW) variant_type タグ追加 (= Phase 0 前段).

依頼: 2026-05-29_tcg_variant_completeness_feasibility.md ユーザー判定「着手」

目的:
  既存 catalog entries の image_url + product_id を解析し、
  specs.variant_type に分類タグを追加 (= 既存 entry の変更のみ、 新規 INSERT なし)。

variant_type 分類規則 (= 優先順):
  1. promo       — image URL に `/P/` または product_id に `_P_` 含む
  2. leader      — image URL に `/L/` 含む (= Leader card)
  3. premium_booster — image URL に `/PRB\d+/` (= 例 PRB01 / PRB02)
  4. starter_deck — image URL に `/ST\d+/` 含む (例 ST24)
  5. event       — image URL に `/EB\d+/` 含む (Event Booster)
  6. other_product — image URL に `/Other Product Card/`
  7. parallel     — product_id suffix `_p` `_p1` `_p2` (= 数字つき)
  8. alt_art      — product_id suffix `_alt`
  9. pre_release  — product_id suffix `_d` `_dummy` `_sample` (= 旧 marker)
  10. (default = base)

実行:
  python iMakCatalog/migrations/2026-05-29_bandai_3cat_variant_type_tagging.py --probe
  python iMakCatalog/migrations/2026-05-29_bandai_3cat_variant_type_tagging.py
"""
from __future__ import annotations

import argparse
import json
import re
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

DB_PATH = str(api._DB_PATH)
NOW = datetime.now().isoformat()

CATEGORIES = ["one_piece_tcg", "gundam_tcg", "dragonball_scg"]

# image URL path → variant_type (= 優先順)
_URL_TYPE_PRIORITY = [
    (re.compile(r"/Other Product Card/", re.IGNORECASE), "other_product"),
    (re.compile(r"/PRB\d+/", re.IGNORECASE), "premium_booster"),
    (re.compile(r"/L/", re.IGNORECASE), "leader"),
    (re.compile(r"/ST\d+/", re.IGNORECASE), "starter_deck"),
    (re.compile(r"/EB\d+/", re.IGNORECASE), "event"),
    (re.compile(r"/P/", re.IGNORECASE), "promo"),
]

# product_id suffix → variant_type
_SUFFIX_TYPE_PATTERNS = [
    (re.compile(r"_alt\b", re.IGNORECASE), "alt_art"),
    (re.compile(r"_(SUPERPARA|PARA|para)\b"), "parallel"),
    (re.compile(r"_p\d+\b"), "parallel"),
    (re.compile(r"_(BETA|beta)\b"), "beta"),
    (re.compile(r"_(dummy|sample|nonotforsale|notforsale)\b", re.IGNORECASE), "pre_release"),
    (re.compile(r"_d\b"), "pre_release_dummy"),
]


def classify(product_id: str, images: list[str]) -> str | None:
    """variant_type 推定 (= 優先順)。 不明 = None (= base)。"""
    for img in images:
        for pat, tag in _URL_TYPE_PRIORITY:
            if pat.search(img):
                return tag
    for pat, tag in _SUFFIX_TYPE_PATTERNS:
        if pat.search(product_id):
            return tag
    return None


def process_category(db: sqlite3.Connection, cat: str, dry_run: bool) -> dict:
    rs = db.execute(
        "SELECT id, product_id, images, specs FROM products WHERE category=?", (cat,)
    ).fetchall()
    counts: Counter = Counter()
    updated = 0
    for r in rs:
        try:
            imgs = json.loads(r[2]) if r[2] else []
        except Exception:
            imgs = []
        try:
            specs = json.loads(r[3]) if r[3] else {}
        except Exception:
            specs = {}
        vt = classify(r[1], imgs)
        if vt is None:
            counts["base"] += 1
            continue
        if specs.get("variant_type") == vt:
            counts[f"already:{vt}"] += 1
            continue
        counts[vt] += 1
        if dry_run:
            continue
        specs["variant_type"] = vt
        db.execute(
            "UPDATE products SET specs=?, updated_at=? WHERE id=?",
            (json.dumps(specs, ensure_ascii=False), NOW, r[0]),
        )
        updated += 1
    if not dry_run:
        db.commit()
    counts["__updated__"] = updated
    counts["__total__"] = len(rs)
    return dict(counts)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--probe", action="store_true", help="dry-run (= 集計のみ、 DB 変更なし)")
    args = p.parse_args()

    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row

    print(f"=== variant_type tagging ({'DRY-RUN' if args.probe else 'APPLY'}) ===\n")
    grand_updated = 0
    for cat in CATEGORIES:
        print(f"--- {cat} ---")
        result = process_category(db, cat, dry_run=args.probe)
        total = result.pop("__total__")
        updated = result.pop("__updated__")
        for k in sorted(result.keys()):
            print(f"  {k:<25} {result[k]}")
        print(f"  TOTAL ENTRIES:           {total}")
        print(f"  UPDATED (or would):      {updated if not args.probe else sum(v for k,v in result.items() if not k.startswith('already') and k != 'base')}")
        print()
        grand_updated += updated

    db.close()
    if not args.probe:
        print(f"=== grand updated: {grand_updated} ===")


if __name__ == "__main__":
    main()
