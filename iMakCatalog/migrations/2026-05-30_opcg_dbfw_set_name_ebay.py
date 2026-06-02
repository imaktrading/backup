"""Phase G-1: OPCG + DBFW set_name_ebay 投入 (= Bandai EN set 名).

依頼: 2026-05-30_phase_g_set_name_ebay_opcg_pokemon_dbfw_priority.md

flow:
  1. Bandai EN list_all_cards で全 EN card 取得
  2. set_id ごとに代表 detail で card_set (= EN set 名) 取得
  3. catalog の各 entry に対し:
     - product_id の base card_number で Bandai EN list と join
     - card_set_id → set_name_ebay 投入

実行:
  python iMakCatalog/migrations/2026-05-30_opcg_dbfw_set_name_ebay.py --cat opcg --probe
  python iMakCatalog/migrations/2026-05-30_opcg_dbfw_set_name_ebay.py --cat opcg
  python iMakCatalog/migrations/2026-05-30_opcg_dbfw_set_name_ebay.py --cat dbfw
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scrapers"))
import api  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

DB_PATH = str(api._DB_PATH)
NOW = datetime.now().isoformat()

CAT_CONFIG = {
    "opcg": {
        "scraper_module": "one_piece_tcg",
        "category": "one_piece_tcg",
        "mapping_file": "C:/dev/iMak_data/catalog/_opcg_en_set_mapping.json",
    },
    "dbfw": {
        "scraper_module": "dragonball_scg",
        "category": "dragonball_scg",
        "mapping_file": "C:/dev/iMak_data/catalog/_dbfw_en_set_mapping.json",
    },
    "gundam": {
        "scraper_module": "gundam_tcg",
        "category": "gundam_tcg",
        "mapping_file": "C:/dev/iMak_data/catalog/_gundam_en_set_mapping.json",
    },
}


def build_set_mapping(scraper_mod, mapping_file: Path):
    if mapping_file.exists():
        return json.loads(mapping_file.read_text(encoding="utf-8"))
    print("  fetching EN list ...")
    en = scraper_mod.list_all_cards(scraper_mod.GAME_ID_EN)
    print(f"  EN cards: {len(en):,}")
    set_id_rep = {}
    for c in en:
        sid = c.get("card_set_id")
        if sid and sid not in set_id_rep:
            set_id_rep[sid] = c.get("id")
    print(f"  unique set_id: {len(set_id_rep)}")
    mapping = {}
    for i, (sid, api_id) in enumerate(set_id_rep.items(), 1):
        d = scraper_mod.get_detail(api_id=api_id, language="EN")
        if d:
            mapping[str(sid)] = d.get("card_set", "")
        if i % 10 == 0:
            print(f"  ... {i}/{len(set_id_rep)}")
        time.sleep(0.3)
    mapping_file.write_text(
        json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return mapping


def build_card_to_setid(scraper_mod) -> dict:
    """card_number / image_url / product_id 風キーで set_id を引ける mapping."""
    en = scraper_mod.list_all_cards(scraper_mod.GAME_ID_EN)
    # key 候補: card_number 単独 (= base), image URL filename 部分
    cn_to_setid = {}
    for c in en:
        cn = c.get("card_number")
        sid = c.get("card_set_id")
        if not (cn and sid):
            continue
        # 同 card_number で複数 set ある場合は image_url の set folder で判別必要
        # ただし catalog product_id だけだと image 情報不足、 ベース card_number で代表 set
        if cn not in cn_to_setid:
            cn_to_setid[cn] = sid
    return cn_to_setid


def process(cat_key: str, dry_run: bool):
    cfg = CAT_CONFIG[cat_key]
    import importlib
    mod = importlib.import_module(cfg["scraper_module"])
    print(f"=== Phase G-1 {cat_key} ===")
    mapping_file = Path(cfg["mapping_file"])
    set_mapping = build_set_mapping(mod, mapping_file)
    print(f"  set_id → name: {len(set_mapping)}")
    cn_to_setid = build_card_to_setid(mod)
    print(f"  card_number → set_id: {len(cn_to_setid)}")

    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    rs = db.execute(
        "SELECT id, product_id, specs FROM products WHERE category=?",
        (cfg["category"],),
    ).fetchall()
    updated = 0
    no_match = 0
    for r in rs:
        try:
            specs = json.loads(r["specs"]) if r["specs"] else {}
        except Exception:
            specs = {}
        if "set_name_ebay" in specs:
            continue
        # product_id から base card_number 抽出
        m = re.match(r"^([A-Z]+\d+-\d+)", r["product_id"])
        if not m:
            no_match += 1
            continue
        cn = m.group(1)
        sid = cn_to_setid.get(cn)
        if sid is None:
            no_match += 1
            continue
        set_name_ebay = set_mapping.get(str(sid), "")
        if not set_name_ebay:
            no_match += 1
            continue
        specs["set_name_ebay"] = set_name_ebay
        if not dry_run:
            db.execute(
                "UPDATE products SET specs=?, updated_at=? WHERE id=?",
                (json.dumps(specs, ensure_ascii=False), NOW, r["id"]),
            )
        updated += 1
    if not dry_run:
        db.commit()
    db.close()
    print(f"  updated: {updated:,} | no_match: {no_match:,}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--cat", choices=list(CAT_CONFIG.keys()), required=True)
    p.add_argument("--probe", action="store_true")
    args = p.parse_args()
    process(args.cat, args.probe)


if __name__ == "__main__":
    main()
