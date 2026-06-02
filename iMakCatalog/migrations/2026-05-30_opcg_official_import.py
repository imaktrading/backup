"""OPCG 公式 onepiece-cardgame.com JSON dump → catalog upsert.

依頼: ユーザー指示 (2026-05-30) 「限定商品 175 件含む 公式 series 全 + 全 TCG 網羅」
+ OPCG 公式 limited variant が Bandai TCG+ に無いため別 source 必要。

flow:
  1. _opcg_official_dumps/series_NNNNNN.json を全件読込
  2. 各 card を catalog upsert:
     - 既存 product_id 一致 → source += "+opcg_official"、 spec 補完
     - 不一致 → 新規 INSERT
  3. variant_type タグも同時投入

field mapping (= 公式 → catalog specs):
  cost           ← cost
  power          ← power
  counter        ← counter
  color          ← color
  block          ← block
  feature        ← feature (= 特徴/能力グループ)
  text           ← text (= 効果文)
  attribute      ← attribute (= 打/斬/特/知)
  get_info       ← get_info (= 入手方法/商品名)
  type           ← type (= CHARACTER/LEADER/EVENT/STAGE)
  rarity         ← rarity (= C/UC/R/SR/L/SP/SR-A)
  card_number    ← card_number (= base 部分、例 OP01-001)
  name_jp        ← name_jp

実行:
  python iMakCatalog/migrations/2026-05-30_opcg_official_import.py --probe
  python iMakCatalog/migrations/2026-05-30_opcg_official_import.py
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
DUMP_DIR = Path("C:/dev/iMak_data/catalog/_opcg_official_dumps")
NOW = datetime.now().isoformat()


def _merged_source(existing: str | None, new: str) -> str:
    if not existing:
        return new
    parts = [p.strip() for p in existing.split("+") if p.strip()]
    if new not in parts:
        parts.append(new)
    return "+".join(parts)


def _classify_variant(product_id: str, get_info: str) -> str | None:
    """product_id suffix + get_info で variant_type 推定."""
    pid = product_id
    if re.search(r"_p\d+\b", pid):
        # _p1/_p2/.. 系は 公式の variant = Alt Art / Promo 様
        # get_info でさらに分類 (= 限定/プロモ/イベント)
        gi = (get_info or "").lower()
        if "限定" in gi or "limited" in gi:
            return "limited_product"
        if "プロモ" in gi or "promotion" in gi:
            return "promo"
        if "ファミリー" in gi:
            return "family_deck"
        return "alt_art"  # _pN suffix + 特殊 get_info → 通常 alt art
    return None


def _build_specs(entry: dict, existing_specs: dict | None) -> dict:
    specs = dict(existing_specs) if existing_specs else {}
    for k_src, k_dst in [
        ("cost", "cost"),
        ("power", "power"),
        ("counter", "counter"),
        ("color", "color"),
        ("block", "block"),
        ("feature", "feature"),
        ("text", "card_text"),
        ("attribute", "attribute"),
        ("get_info", "get_info"),
        ("type", "card_type"),
        ("rarity", "rarity"),
    ]:
        v = entry.get(k_src)
        if v:
            specs[k_dst] = v
    # variant_type (= 既存タグ尊重しつつ Alt Art 判定上書き)
    vt = _classify_variant(entry.get("card_id", ""), entry.get("get_info", ""))
    if vt:
        # 既存 'parallel' タグでも opcg_official 由来の alt_art / limited_product / promo は上書き
        if specs.get("variant_type") in (None, "parallel"):
            specs["variant_type"] = vt
    return specs


def upsert_entry(db: sqlite3.Connection, entry: dict, dry_run: bool) -> str:
    pid = entry.get("card_id")
    if not pid:
        return "SKIP"
    name = entry.get("name_jp", "")
    image = entry.get("image_url", "")
    cn = entry.get("card_number", "")
    set_name = entry.get("get_info", "") or ""

    existing = db.execute(
        "SELECT id, specs, source, name_jp, images, set_name_official FROM products "
        "WHERE category='one_piece_tcg' AND product_id=?",
        (pid,),
    ).fetchone()

    if existing:
        try:
            old_specs = json.loads(existing[1]) if existing[1] else {}
        except Exception:
            old_specs = {}
        new_specs = _build_specs(entry, old_specs)
        new_source = _merged_source(existing[2], "opcg_official")
        # 既存 images に重複追加防ぐ
        try:
            old_images = json.loads(existing[4]) if existing[4] else []
        except Exception:
            old_images = []
        new_images = list(old_images)
        if image and image not in new_images:
            new_images.append(image)
        new_set = existing[5] or set_name
        # name_jp が既存空なら補完
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
                "one_piece_tcg", pid, name or pid, name, set_name,
                json.dumps(new_specs, ensure_ascii=False),
                json.dumps([image] if image else [], ensure_ascii=False),
                "opcg_official",
                f"https://www.onepiece-cardgame.com/cardlist/?series={entry.get('series_id','')}",
                NOW, NOW,
            ),
        )
        return "INSERT"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--probe", action="store_true", help="dry-run")
    args = p.parse_args()

    files = sorted(DUMP_DIR.glob("series_*.json"))
    if not files:
        print("no dump files")
        return
    print(f"=== OPCG 公式 import: {len(files)} series ===")
    db = sqlite3.connect(DB_PATH)
    total = {"INSERT": 0, "UPDATE": 0, "SKIP": 0}
    for f in files:
        data = json.loads(f.read_text(encoding="utf-8"))
        sid = data.get("series_id", "")
        sname = data.get("series_name", "")
        cards = data.get("cards", [])
        counts = {"INSERT": 0, "UPDATE": 0, "SKIP": 0}
        for c in cards:
            c["series_id"] = sid
            r = upsert_entry(db, c, dry_run=args.probe)
            counts[r] += 1
            total[r] += 1
        if not args.probe:
            db.commit()
        print(f"  {sid} ({sname[:30]:<30}) cards={len(cards):>3} {counts}")
    db.close()
    print(f"\n=== total ===")
    print(f"  INSERT: {total['INSERT']}")
    print(f"  UPDATE: {total['UPDATE']}")
    print(f"  SKIP:   {total['SKIP']}")


if __name__ == "__main__":
    main()
