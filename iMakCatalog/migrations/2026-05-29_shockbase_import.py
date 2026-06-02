"""ShockBase JSON dump → catalog (gshock) upsert.

依頼: ユーザー指示 (5/29) 「ShockBase を発売年の新しい順に取得していって」
+ POC 結果 (= 2026-05-29_shockbase_poc_go_sampling_processed.md) 案 C 採用。

flow:
  1. _shockbase_dumps/year_YYYY_batch_NNN.json を順次読込
  2. 各 entry を gshock category に upsert:
     - 既存 product_id 一致 → source ラベル += ",shockbase"、 ShockBase 専有 field 追加
     - 不一致 → 新規 INSERT (= source="shockbase")
  3. 投入結果 log + 進捗 report

field mapping (= ShockBase → catalog specs):
  case_size      ← SIZE_(HXWXT) [2nd]
  case_thickness ← SIZE_(HXWXT) [3rd]
  band_material  ← BAND
  bezel_material ← BEZEL
  band_color     ← COLOR_BAND
  bezel_color    ← COLOR_BEZEL
  dial_color     ← COLOR_WATCHFACE
  crystal        ← GLASS
  weight         ← WEIGHT (= "Unknown" は空欄)
  year           ← RELEASE から数字抽出
  series         ← SUBSERIES
  is_limited     ← LIMITED_EDITION == "Yes"
  is_collab      ← SPECIAL_EDITION の有無
  features       ← FEATURES_ON (= 配列)
  water_resistance ← FEATURES_ON 内 water_resistance:_XXXm

ShockBase 専有 field (= specs に新規 key):
  module         ← MODULE
  nickname       ← NICKNAME
  collection     ← COLLECTION
  battery        ← BATTERY
  battery_life   ← BATTERY_LIFE
  lcd_type       ← LCD_TYPE
  light_type     ← LIGHT_TYPE
  display_polarity ← DISPLAY (= "Negative" 等)
  release_by_country ← {EUROPE, JAPAN, ...} dict
  features_off   ← FEATURES_OFF (= 配列、 デバッグ/監査用)

実行:
  python iMakCatalog/migrations/2026-05-29_shockbase_import.py --probe  # 最初の 5 件で投入予行
  python iMakCatalog/migrations/2026-05-29_shockbase_import.py          # 全 batch 投入
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
DUMP_DIR = Path("C:/dev/iMak_data/catalog/_shockbase_dumps")
NOW = datetime.now().isoformat()

COUNTRY_KEYS = [
    "EUROPE", "UK", "USA", "CANADA", "CHINA", "JAPAN", "TAIWAN", "THAILAND",
    "INDIA", "INDONESIA", "MALAYSIA", "BRASIL", "PHILIPPINES", "SINGAPORE",
    "MEXICO", "CAMBODIA", "SOUTH_AFRICA", "SOUTH_KOREA", "HONG_KONG",
    "VIETNAM", "TURKEY", "MIDDLE_EAST",
]


def _parse_size(size_str: str) -> tuple[str, str]:
    """SIZE_(HXWXT) "48.5 x 45.4 x 11.8 mm" → (case_size=45.4 mm, case_thickness=11.8 mm)."""
    if not size_str:
        return "", ""
    m = re.match(r"([\d.]+)\s*x\s*([\d.]+)\s*x\s*([\d.]+)\s*mm", size_str)
    if not m:
        return "", ""
    # H x W x T → case_size = W、 case_thickness = T (= 既存 catalog 流儀)
    return f"{m.group(2)} mm", f"{m.group(3)} mm"


def _parse_year(release_str: str) -> str:
    if not release_str:
        return ""
    m = re.search(r"(\d{4})", release_str)
    return m.group(1) if m else ""


def _parse_water_resistance(features_on: list[str]) -> str:
    for f in features_on:
        m = re.match(r"water_resistance:_(\d+)m", f)
        if m:
            return f"{m.group(1)} m"
    return ""


def _has_special_edition(entry: dict) -> bool:
    return bool(entry.get("SPECIAL_EDITION", "").strip())


def _build_specs(entry: dict, existing_specs: dict | None) -> dict:
    """ShockBase entry → specs dict 構築.

    既存 specs があれば、 ShockBase で field 単位 merge (= 案 C 優先順位):
      - case_size / case_thickness / year / series / nickname / module / battery /
        battery_life / lcd_type / light_type / release_by_country / features_off
        → ShockBase 優先
      - band_color / bezel_color / dial_color / weight (= ShockBase に Unknown 多)
        → 既存値 > ShockBase
      - case_material (= ShockBase に無い)
        → 既存値維持
      - features (= ON list)
        → 既存 + ShockBase 統合 (= dedup)
    """
    specs = dict(existing_specs) if existing_specs else {}
    case_size, case_thickness = _parse_size(entry.get("SIZE_(HXWXT)", ""))
    year = _parse_year(entry.get("RELEASE", ""))
    features_on = entry.get("FEATURES_ON", []) or []
    features_off = entry.get("FEATURES_OFF", []) or []
    water_res = _parse_water_resistance(features_on)

    # ShockBase 優先 field
    if case_size:
        specs["case_size"] = case_size
    if case_thickness:
        specs["case_thickness"] = case_thickness
    if year:
        specs["year"] = year
    if entry.get("SUBSERIES"):
        specs["series"] = entry["SUBSERIES"]
    if water_res:
        specs["water_resistance"] = water_res
    # ShockBase 専有 (= 新規 key)
    if entry.get("MODULE"):
        specs["module"] = entry["MODULE"]
    if entry.get("NICKNAME"):
        specs["nickname"] = entry["NICKNAME"]
    if entry.get("COLLECTION"):
        specs["collection"] = entry["COLLECTION"]
    if entry.get("BATTERY"):
        specs["battery"] = entry["BATTERY"]
    if entry.get("BATTERY_LIFE"):
        specs["battery_life"] = entry["BATTERY_LIFE"]
    if entry.get("LCD_TYPE"):
        specs["lcd_type"] = entry["LCD_TYPE"]
    if entry.get("LIGHT_TYPE"):
        specs["light_type"] = entry["LIGHT_TYPE"]
    if entry.get("DISPLAY"):
        specs["display_polarity"] = entry["DISPLAY"]
    if entry.get("SPECIAL_EDITION"):
        specs["special_edition"] = entry["SPECIAL_EDITION"]

    # 既存値 > ShockBase の field (= 空ならば ShockBase 採用)
    for cat_key, sb_key in [
        ("band_material", "BAND"),
        ("bezel_material", "BEZEL"),
        ("band_color", "COLOR_BAND"),
        ("bezel_color", "COLOR_BEZEL"),
        ("dial_color", "COLOR_WATCHFACE"),
        ("crystal", "GLASS"),
    ]:
        if not specs.get(cat_key):
            v = entry.get(sb_key, "")
            if v:
                specs[cat_key] = v

    # weight (= ShockBase "Unknown" の場合 既存値維持)
    w = entry.get("WEIGHT", "")
    if w and w.lower() != "unknown" and not specs.get("weight"):
        specs["weight"] = w

    # is_limited / is_collab
    if entry.get("LIMITED_EDITION", "").lower() == "yes":
        specs["is_limited"] = True
    if _has_special_edition(entry):
        specs["is_collab"] = True

    # features 統合 (= 既存 + FEATURES_ON、 dedup)
    existing_features = specs.get("features") or []
    if not isinstance(existing_features, list):
        existing_features = []
    merged = set(existing_features) | set(features_on)
    if merged:
        specs["features"] = sorted(merged)

    # ShockBase 専有監査用
    if features_off:
        specs["features_off_shockbase"] = sorted(set(features_off))

    # 国別 release date dict
    rel_by_country = {}
    for k in COUNTRY_KEYS:
        v = entry.get(k, "")
        if v and v.lower() != "no information":
            rel_by_country[k] = v
    if rel_by_country:
        specs["release_by_country"] = rel_by_country

    return specs


def _merged_source(existing: str | None, new: str) -> str:
    if not existing:
        return new
    parts = [p.strip() for p in existing.split("+") if p.strip()]
    if new not in parts:
        parts.append(new)
    return "+".join(parts)


def upsert_entry(db: sqlite3.Connection, entry: dict, dry_run: bool = False) -> str:
    """1 entry を gshock category に upsert.

    Returns: 'INSERT' | 'UPDATE' | 'SKIP'
    """
    pid = entry.get("__model__") or entry.get("MODEL")
    if not pid:
        return "SKIP"
    url = entry.get("__url__", "")

    existing = db.execute(
        "SELECT id, specs, source FROM products WHERE category='gshock' AND product_id=?",
        (pid,),
    ).fetchone()

    name_fallback = f"Casio G-SHOCK {pid}"
    if existing:
        try:
            old_specs = json.loads(existing[1]) if existing[1] else {}
        except Exception:
            old_specs = {}
        new_specs = _build_specs(entry, old_specs)
        new_source = _merged_source(existing[2], "shockbase")
        if dry_run:
            return "UPDATE"
        db.execute(
            "UPDATE products SET specs=?, source=?, source_url=?, updated_at=? WHERE id=?",
            (json.dumps(new_specs, ensure_ascii=False), new_source, url, NOW, existing[0]),
        )
        return "UPDATE"
    else:
        new_specs = _build_specs(entry, None)
        if dry_run:
            return "INSERT"
        db.execute(
            """INSERT INTO products
               (category, product_id, name, name_en, name_en_source, specs, images, source, source_url, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "gshock", pid, name_fallback, name_fallback, "product_id_native_english",
                json.dumps(new_specs, ensure_ascii=False),
                json.dumps([]),
                "shockbase", url, NOW, NOW,
            ),
        )
        return "INSERT"


def process_batch_file(db: sqlite3.Connection, batch_file: Path, dry_run: bool = False, limit: int | None = None) -> dict:
    data = json.loads(batch_file.read_text(encoding="utf-8"))
    if limit:
        data = data[:limit]
    counts = {"INSERT": 0, "UPDATE": 0, "SKIP": 0}
    for entry in data:
        r = upsert_entry(db, entry, dry_run=dry_run)
        counts[r] += 1
    if not dry_run:
        db.commit()
    return counts


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--probe", action="store_true", help="dry-run + 5 件で予行")
    p.add_argument("--limit", type=int, help="件数制限 (= test 用)")
    p.add_argument("--batch", type=str, help="特定 batch file のみ処理 (= filename)")
    args = p.parse_args()

    if not DUMP_DIR.exists():
        print(f"dump dir not found: {DUMP_DIR}")
        return

    batches = sorted(DUMP_DIR.glob("year_*_batch_*.json"))
    if args.batch:
        batches = [b for b in batches if b.name == args.batch]
    if not batches:
        print("no batch files to process")
        return

    print(f"=== ShockBase import: {len(batches)} batch file(s) ===")
    db = sqlite3.connect(DB_PATH)
    total = {"INSERT": 0, "UPDATE": 0, "SKIP": 0}
    for bf in batches:
        if args.probe:
            counts = process_batch_file(db, bf, dry_run=True, limit=5)
            print(f"  {bf.name}: [dry-run 5] {counts}")
        else:
            counts = process_batch_file(db, bf, dry_run=False, limit=args.limit)
            print(f"  {bf.name}: {counts}")
            for k in total:
                total[k] += counts[k]
    db.close()
    print(f"\n=== total ===")
    print(f"  INSERT: {total['INSERT']}")
    print(f"  UPDATE: {total['UPDATE']}")
    print(f"  SKIP:   {total['SKIP']}")


if __name__ == "__main__":
    main()
