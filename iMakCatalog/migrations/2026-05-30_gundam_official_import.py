"""Gundam 公式 gundam-gcg.com JSON dump → catalog upsert.

依頼: ユーザー指示 (2026-05-30) 「公式 source 全 TCG 網羅」
+ OPCG 公式 import (= 2026-05-30_opcg_official_import.py) と同 pattern。

field mapping (= 公式 → catalog specs):
  Lv.            → level
  COST           → cost
  色             → color
  タイプ          → card_type
  地形           → terrain
  特徴           → feature
  リンク          → link_condition
  AP             → ap
  HP             → hp
  出典タイトル     → source_title
  入手           → get_info
  image_url      → images に追加

実行:
  python iMakCatalog/migrations/2026-05-30_gundam_official_import.py --probe
  python iMakCatalog/migrations/2026-05-30_gundam_official_import.py
"""
from __future__ import annotations

import argparse
import json
import re
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
DUMP_DIR = Path("C:/dev/iMak_data/catalog/_gundam_official_dumps")
NOW = datetime.now().isoformat()

# Gundam 公式 field 名 → catalog specs key
FIELD_MAP = {
    "Lv.": "level",
    "COST": "cost",
    "色": "color",
    "タイプ": "card_type",
    "地形": "terrain",
    "特徴": "feature",
    "リンク": "link_condition",
    "AP": "ap",
    "HP": "hp",
    "出典タイトル": "source_title",
    "入手": "get_info",
}


def _merged_source(existing: str | None, new: str) -> str:
    if not existing:
        return new
    parts = [p.strip() for p in existing.split("+") if p.strip()]
    if new not in parts:
        parts.append(new)
    return "+".join(parts)


def _classify_variant(product_id: str, get_info: str) -> str | None:
    pid = product_id
    if re.search(r"_p\d+\b", pid):
        gi = (get_info or "").lower()
        if "限定" in gi:
            return "limited_product"
        if "プロモ" in gi or "promo" in gi:
            return "promo"
        return "alt_art"
    return None


def _build_specs(entry: dict, existing_specs: dict | None) -> dict:
    specs = dict(existing_specs) if existing_specs else {}
    for src_key, dst_key in FIELD_MAP.items():
        v = entry.get(src_key)
        if v:
            specs[dst_key] = v
    # 既存 base 系 (= Card Type / Color 等 大文字始) があれば、 公式値を採用 (= 統一)
    vt = _classify_variant(entry.get("card_id", ""), entry.get("入手", ""))
    if vt and specs.get("variant_type") in (None, "parallel"):
        specs["variant_type"] = vt
    return specs


def upsert_entry(db: sqlite3.Connection, entry: dict, dry_run: bool) -> str:
    pid = entry.get("card_id")
    if not pid:
        return "SKIP"
    name = entry.get("name_jp", "") or ""
    image = entry.get("image_url", "")
    set_name = entry.get("入手", "") or entry.get("series_name", "")

    existing = db.execute(
        "SELECT id, specs, source, name_jp, images, set_name_official FROM products "
        "WHERE category='gundam_tcg' AND product_id=?",
        (pid,),
    ).fetchone()

    if existing:
        try:
            old_specs = json.loads(existing[1]) if existing[1] else {}
        except Exception:
            old_specs = {}
        new_specs = _build_specs(entry, old_specs)
        new_source = _merged_source(existing[2], "gundam_official")
        try:
            old_images = json.loads(existing[4]) if existing[4] else []
        except Exception:
            old_images = []
        new_images = list(old_images)
        if image and image not in new_images:
            new_images.append(image)
        new_set = existing[5] or set_name
        new_name_jp = existing[3] or name
        if dry_run:
            return "UPDATE"
        db.execute(
            """UPDATE products
               SET specs=?, source=?, images=?, name_jp=?, set_name_official=?, updated_at=?
               WHERE id=?""",
            (
                json.dumps(new_specs, ensure_ascii=False),
                new_source,
                json.dumps(new_images, ensure_ascii=False),
                new_name_jp,
                new_set,
                NOW,
                existing[0],
            ),
        )
        return "UPDATE"
    else:
        new_specs = _build_specs(entry, None)
        if dry_run:
            return "INSERT"
        db.execute(
            """INSERT INTO products
               (category, product_id, name, name_jp, set_name_official,
                specs, images, source, source_url, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "gundam_tcg", pid, name or pid, name, set_name,
                json.dumps(new_specs, ensure_ascii=False),
                json.dumps([image] if image else [], ensure_ascii=False),
                "gundam_official",
                entry.get("url", ""),
                NOW, NOW,
            ),
        )
        return "INSERT"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--probe", action="store_true")
    args = p.parse_args()
    files = sorted(DUMP_DIR.glob("series_*.json"))
    if not files:
        print("no dump files")
        return
    print(f"=== Gundam 公式 import: {len(files)} series ===")
    db = sqlite3.connect(DB_PATH)
    total = {"INSERT": 0, "UPDATE": 0, "SKIP": 0}
    for f in files:
        data = json.loads(f.read_text(encoding="utf-8"))
        sid = data.get("series_id", "")
        sname = data.get("series_name", "")
        cards = data.get("cards", [])
        counts = {"INSERT": 0, "UPDATE": 0, "SKIP": 0}
        for c in cards:
            c.setdefault("series_id", sid)
            c.setdefault("series_name", sname)
            r = upsert_entry(db, c, dry_run=args.probe)
            counts[r] += 1
            total[r] += 1
        if not args.probe:
            db.commit()
        print(f"  {sid} ({sname[:25]:<25}) cards={len(cards):>3} {counts}")
    db.close()
    print(f"\n=== total ===")
    print(f"  INSERT: {total['INSERT']}")
    print(f"  UPDATE: {total['UPDATE']}")
    print(f"  SKIP:   {total['SKIP']}")


if __name__ == "__main__":
    main()
