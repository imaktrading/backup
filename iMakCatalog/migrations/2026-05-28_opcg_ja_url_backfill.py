"""OPCG JA URL backfill — EN only catalog entries に Bandai TCG+ JA URL 追加投入.

依頼: 2026-05-28_catalog_opcg_ja_image_url_scrape.md

実装:
  1. Bandai TCG+ JA 全件 fetch (= game_title_id=8 OPCG JA)
  2. {(card_number, card_set_id): image_url} 辞書化
  3. catalog EN-only entries (= 1,684 件) を update
     - product_id + card_set_id (from specs) で JA URL マッチ
     - 既存 images 配列に JA URL append (= EN URL は保持)
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scrapers"))
import api  # noqa: E402
import one_piece_tcg as op  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

DB = str(api._DB_PATH)
NOW = datetime.now().isoformat()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--probe", action="store_true", help="件数集計のみ")
    p.add_argument("--dry-run", action="store_true", help="DB 触らず投入 plan 表示")
    p.add_argument("--limit", type=int, help="先頭 N 件のみ")
    args = p.parse_args()

    # 1. EN only entries 抽出
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    targets = []
    for r in db.execute("SELECT id, product_id, card_set_id, images FROM products WHERE category='one_piece_tcg'").fetchall():
        try:
            imgs = json.loads(r["images"]) if r["images"] else []
        except Exception:
            imgs = []
        has_ja = any("/OP-JA/" in u for u in imgs)
        has_en = any("/OP-EN/" in u for u in imgs)
        if has_en and not has_ja:
            targets.append({
                "id": r["id"],
                "product_id": r["product_id"],
                "card_set_id": r["card_set_id"],
                "images": imgs,
            })
    print(f"EN-only targets: {len(targets)}")

    if args.probe:
        db.close()
        return

    if args.limit:
        targets = targets[: args.limit]

    # 2. Bandai TCG+ JA 全件 fetch + 辞書化
    # 注: card_set_id は EN/JA で別 ID = matching に使えない
    # URL path の set 部分 (= /OP-JA/{SET}/) で match
    print(f"\nBandai TCG+ JA 全件 fetch ...")
    ja_cards = op.list_all_cards(op.GAME_ID_JA)
    print(f"  JA total: {len(ja_cards)}")
    import re
    ja_index: dict[tuple[str, str], list[str]] = {}
    for c in ja_cards:
        cn = c.get("card_number")
        url = c.get("image_url")
        if not (cn and url):
            continue
        m = re.search(r"/OP-JA/([^/]+)/", url)
        if not m:
            continue
        url_set = m.group(1)
        key = (cn, url_set)
        ja_index.setdefault(key, []).append(url)
    print(f"  ja_index built: {len(ja_index)} unique (cn, url_set) pairs")

    # cn-only index も同時に build (= fallback 用)
    ja_index_cn: dict[str, list[str]] = {}
    for (cn, url_set), urls in ja_index.items():
        ja_index_cn.setdefault(cn, []).extend(urls)

    # 3. matching + UPDATE (= EN URL の set path で対応 JA URL 検索)
    print(f"\n=== matching + UPDATE ===")
    updated, matched_primary, matched_fallback, no_match = 0, 0, 0, 0
    for t in targets:
        # EN URL から url_set 抽出
        en_url_set = None
        for u in t["images"]:
            m = re.search(r"/OP-EN/([^/]+)/", u)
            if m:
                en_url_set = m.group(1)
                break
        # product_id から card_number 抽出
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
                matched_primary += 1
        # fallback: cn の prefix set を含む JA URL を試行
        if not ja_url:
            cn_prefix = base_card_number.split("-")[0]  # = 例 'EB02', 'OP15'
            cand_all = ja_index_cn.get(base_card_number) or []
            # cn の prefix set を url path に含む URL を最優先
            preferred = [u for u in cand_all if f"/OP-JA/{cn_prefix}/" in u]
            if preferred:
                ja_url = preferred[0]
                matched_fallback += 1
            elif cand_all:
                ja_url = cand_all[0]
                matched_fallback += 1

        if not ja_url:
            no_match += 1
            continue
        if ja_url in t["images"]:
            continue
        new_images = t["images"] + [ja_url]
        if args.dry_run:
            print(f"  [DRY] {pid} → +JA: {ja_url[-60:]}")
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

    if not args.dry_run:
        db.commit()
    db.close()

    print(f"\n=== 完了 ===")
    print(f"  UPDATE:           {updated}")
    print(f"  primary match:    {matched_primary} (= (cn, url_set) 完全一致)")
    print(f"  fallback match:   {matched_fallback} (= cn-only or cn prefix set)")
    print(f"  no match:         {no_match}")
    print(f"  total target:     {len(targets)}")


if __name__ == "__main__":
    main()
