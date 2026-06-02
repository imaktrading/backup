"""Pokemon detail fetch 結果を catalog upsert (= 別 PC 取得分).

依頼: ユーザー指示 (2026-05-30) Pokemon 不足 cardID fetch 完了後の投入

flow:
  1. _pokemon_missing_dumps/_raw_html/{cardID}.html を全件 parse
  2. 既存 pokemon_tcg.py の logic 流用で specs 抽出
  3. catalog upsert (= 既存と product_id 一致なら UPDATE、 新規なら INSERT)

実行:
  python iMakCatalog/migrations/2026-05-30_pokemon_missing_upsert.py --probe
  python iMakCatalog/migrations/2026-05-30_pokemon_missing_upsert.py
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
sys.path.insert(0, str(ROOT / "scrapers"))
import api  # noqa: E402
import pokemon_tcg as pt  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

DB_PATH = str(api._DB_PATH)
NOW = datetime.now().isoformat()
RAW_DIR = Path("C:/Users/imax2/OneDrive/デスクトップ/_pokemon_missing_dumps/_raw_html")


def process(dry_run: bool):
    files = sorted(RAW_DIR.glob("*.html"))
    print(f"=== Pokemon missing upsert ({'DRY-RUN' if dry_run else 'APPLY'}) ===")
    print(f"  raw HTML files: {len(files):,}")
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    counts = {"INSERT": 0, "UPDATE": 0, "SKIP": 0, "PARSE_FAIL": 0}
    for f in files:
        cid = f.stem
        try:
            html = f.read_text(encoding="utf-8")
        except Exception:
            counts["PARSE_FAIL"] += 1
            continue
        parsed = pt._parse_detail_html(html, cid)
        if not parsed:
            counts["PARSE_FAIL"] += 1
            continue
        pid = pt.derive_product_id(parsed)
        if not pid:
            counts["SKIP"] += 1
            continue
        name = parsed.get("name", "") or ""
        image = parsed.get("image_url", "")
        specs = pt.build_specs(parsed)

        existing = db.execute(
            "SELECT id FROM products WHERE category='pokemon_tcg' AND product_id=?",
            (pid,),
        ).fetchone()

        if existing:
            counts["UPDATE"] += 1
            if not dry_run:
                db.execute(
                    "UPDATE products SET name=?, name_jp=?, specs=?, images=?, source_url=?, updated_at=? WHERE id=?",
                    (
                        name, name,
                        json.dumps(specs, ensure_ascii=False),
                        json.dumps([image] if image else [], ensure_ascii=False),
                        f"https://www.pokemon-card.com/card-search/details.php/card/{cid}",
                        NOW, existing["id"],
                    ),
                )
        else:
            counts["INSERT"] += 1
            if not dry_run:
                db.execute(
                    """INSERT INTO products
                       (category, product_id, name, name_jp, set_name, set_name_official,
                        specs, images, source, source_url, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        "pokemon_tcg", pid, name, name,
                        parsed.get("set_name_official", ""),
                        parsed.get("set_name_official", ""),
                        json.dumps(specs, ensure_ascii=False),
                        json.dumps([image] if image else [], ensure_ascii=False),
                        "pokemon-card.com",
                        f"https://www.pokemon-card.com/card-search/details.php/card/{cid}",
                        NOW, NOW,
                    ),
                )
    if not dry_run:
        db.commit()
    db.close()
    print(f"\n=== result ===")
    for k in ("INSERT", "UPDATE", "SKIP", "PARSE_FAIL"):
        print(f"  {k:<12} {counts[k]:>5,}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--probe", action="store_true")
    args = p.parse_args()
    process(dry_run=args.probe)


if __name__ == "__main__":
    main()
