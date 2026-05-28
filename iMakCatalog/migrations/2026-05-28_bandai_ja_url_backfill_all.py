"""Bandai TCG+ 3 カテゴリ (OPCG / Gundam / DragonBall) 一括 JA URL backfill.

依頼: 2026-05-28_catalog_opcg_ja_image_url_scrape.md (= OPCG) の他カテゴリ波及
背景:
  scraper の _variant_key bug A (= JA pre-release marker で leftover 不一致)
  を 3 scraper 全部 fix 済 (= commit 32ebe49 OPCG + 本日 commit Gundam/DBFW)。
  既存 catalog 内 EN-only entries (= 過去 scrape 時の取得漏れ) を JA URL 後付け追加。

flow (= 各 category 独立):
  1. catalog から EN-only entries 抽出
  2. Bandai TCG+ JA API 全件 fetch
  3. URL path で (cn, url_set) primary match
  4. fallback: cn-only + cn prefix set 優先
  5. images 配列に JA URL append (= 冪等)
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
sys.path.insert(0, str(ROOT / "scrapers"))
import api  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

DB = str(api._DB_PATH)
NOW = datetime.now().isoformat()

# カテゴリ別 URL path prefix
CATEGORY_CONFIG = {
    "one_piece_tcg": {
        "scraper_module": "one_piece_tcg",
        "en_path": "/OP-EN/",
        "ja_path": "/OP-JA/",
    },
    "gundam_tcg": {
        "scraper_module": "gundam_tcg",
        "en_path": "/GC-EN/",
        "ja_path": "/GC-JA/",
    },
    "dragonball_scg": {
        "scraper_module": "dragonball_scg",
        "en_path": "/DBFW-EN/",
        "ja_path": "/DBFW-JA/",
    },
}


def backfill_category(category: str, dry_run: bool = False) -> dict:
    """1 category の JA URL backfill 実行."""
    cfg = CATEGORY_CONFIG[category]
    scraper_mod = __import__(cfg["scraper_module"])
    en_path = cfg["en_path"]
    ja_path = cfg["ja_path"]
    en_path_re = re.escape(en_path.strip("/"))
    ja_path_re = re.escape(ja_path.strip("/"))

    print(f"\n{'='*70}")
    print(f"=== {category} backfill ===")
    print(f"{'='*70}")

    # 1. EN-only targets
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    targets = []
    for r in db.execute(
        "SELECT id, product_id, images FROM products WHERE category=?", (category,)
    ).fetchall():
        try:
            imgs = json.loads(r["images"]) if r["images"] else []
        except Exception:
            imgs = []
        has_ja = any(ja_path in u for u in imgs)
        has_en = any(en_path in u for u in imgs)
        if has_en and not has_ja:
            targets.append({
                "id": r["id"],
                "product_id": r["product_id"],
                "images": imgs,
            })
    print(f"EN-only targets: {len(targets)}")

    if not targets:
        db.close()
        return {"category": category, "updated": 0, "no_match": 0, "targets": 0}

    # 2. JA full fetch + dual index
    print(f"Bandai TCG+ JA 全件 fetch ...")
    ja_cards = scraper_mod.list_all_cards(scraper_mod.GAME_ID_JA)
    print(f"  JA total: {len(ja_cards)}")

    ja_index: dict[tuple[str, str], list[str]] = {}
    ja_index_cn: dict[str, list[str]] = {}
    for c in ja_cards:
        cn = c.get("card_number")
        url = c.get("image_url")
        if not (cn and url):
            continue
        m = re.search(rf"/{ja_path_re}/([^/]+)/", url)
        if not m:
            continue
        url_set = m.group(1)
        ja_index.setdefault((cn, url_set), []).append(url)
        ja_index_cn.setdefault(cn, []).append(url)
    print(f"  ja_index pairs: {len(ja_index)} / cn-only: {len(ja_index_cn)}")

    # 3. matching + UPDATE
    updated, no_match, primary, fallback = 0, 0, 0, 0
    for t in targets:
        en_url_set = None
        for u in t["images"]:
            m = re.search(rf"/{en_path_re}/([^/]+)/", u)
            if m:
                en_url_set = m.group(1)
                break
        pid = t["product_id"]
        m = re.match(r"^([A-Z]+\d+-\d+)(_.*)?$", pid)
        if not m:
            no_match += 1
            continue
        base_card_number = m.group(1)

        # primary: (cn, en_url_set) 完全一致
        ja_url = None
        if en_url_set:
            cand = ja_index.get((base_card_number, en_url_set)) or []
            if cand:
                ja_url = cand[0]
                primary += 1
        # fallback: cn-only + prefix set 優先
        if not ja_url:
            cn_prefix = base_card_number.split("-")[0]
            cand_all = ja_index_cn.get(base_card_number) or []
            preferred = [u for u in cand_all if f"/{ja_path_re.replace('/', '/')}/{cn_prefix}/" in u]
            # 上の正規表現の "/" エスケープ不要なため簡略化
            preferred = [u for u in cand_all if f"/{cn_prefix}/" in u]
            if preferred:
                ja_url = preferred[0]
                fallback += 1
            elif cand_all:
                ja_url = cand_all[0]
                fallback += 1
        if not ja_url:
            no_match += 1
            continue
        if ja_url in t["images"]:
            continue
        new_images = t["images"] + [ja_url]
        if dry_run:
            updated += 1
            continue
        db.execute(
            "UPDATE products SET images=?, updated_at=? WHERE id=?",
            (json.dumps(new_images, ensure_ascii=False), NOW, t["id"]),
        )
        updated += 1
        if updated % 200 == 0:
            db.commit()
            print(f"  ... {updated} updated")

    if not dry_run:
        db.commit()
    db.close()

    print(f"\n=== {category} 完了 ===")
    print(f"  UPDATE:        {updated}")
    print(f"  primary:       {primary}")
    print(f"  fallback:      {fallback}")
    print(f"  no match:      {no_match}")
    print(f"  total target:  {len(targets)}")
    return {"category": category, "updated": updated, "no_match": no_match, "targets": len(targets)}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    p.add_argument(
        "--category",
        choices=list(CATEGORY_CONFIG.keys()) + ["all"],
        default="all",
    )
    args = p.parse_args()

    cats = [args.category] if args.category != "all" else list(CATEGORY_CONFIG.keys())
    summary = []
    for c in cats:
        res = backfill_category(c, dry_run=args.dry_run)
        summary.append(res)

    print(f"\n{'='*70}")
    print("=== 全カテゴリ サマリ ===")
    print(f"{'='*70}")
    for s in summary:
        print(f"  {s['category']:<20} UPDATE={s['updated']:>4} / no_match={s['no_match']:>4} / target={s['targets']:>5}")


if __name__ == "__main__":
    main()
