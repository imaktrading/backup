"""Pokemon cardID-XXXX entries (= images=[] fallback) に image_url 補完.

依頼: ユーザー指示 (5/28 21:18) 「カタログは正確な公式データを持つことが目的」
背景:
  catalog Pokemon 67 件が `cardID-XXXXX` fallback + images 空。
  card_number 印字なし promo (= Energy / Movie Card 等) で derive_product_id が
  fallback 形式採用、 ただし detail には pokemon-card.com の image_url 存在。
  scrape 時の build_and_upsert で images 取得漏れ → 後付け補完。

flow:
  1. cardID-XXXX entries 抽出
  2. 各 cardID で pokemon_tcg.get_detail() 再 fetch (= cache 利用)
  3. detail.image_url が ある場合、 catalog images 列に投入
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
import pokemon_tcg as pt  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

DB = str(api._DB_PATH)
NOW = datetime.now().isoformat()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--probe", action="store_true")
    p.add_argument("--limit", type=int)
    args = p.parse_args()

    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    rows = db.execute(
        "SELECT id, product_id, images, source_url FROM products "
        "WHERE category='pokemon_tcg' AND product_id LIKE 'cardID-%'"
    ).fetchall()
    print(f"cardID-XXXX entries: {len(rows)}")

    # 空 image filter
    targets = []
    for r in rows:
        try:
            imgs = json.loads(r["images"]) if r["images"] else []
        except Exception:
            imgs = []
        if imgs:
            continue
        # cardID 抽出
        cid = r["product_id"].replace("cardID-", "")
        if not cid.isdigit():
            continue
        targets.append({
            "id": r["id"],
            "product_id": r["product_id"],
            "cardID": int(cid),
        })
    print(f"images 空 target: {len(targets)}")

    if args.probe:
        return
    if args.limit:
        targets = targets[: args.limit]

    updated, no_img, failed = 0, 0, 0
    started_at = time.time()
    for i, t in enumerate(targets, start=1):
        try:
            detail = pt.get_detail(t["cardID"])
        except Exception as e:
            print(f"  ⚠️ {t['product_id']}: fetch fail {e}")
            failed += 1
            continue
        if not detail:
            failed += 1
            continue
        image_url = detail.get("image_url")
        if not image_url:
            no_img += 1
            continue
        new_images = [image_url]
        db.execute(
            "UPDATE products SET images=?, updated_at=? WHERE id=?",
            (json.dumps(new_images, ensure_ascii=False), NOW, t["id"]),
        )
        updated += 1
        if i % 20 == 0:
            db.commit()
            elapsed = int(time.time() - started_at)
            print(f"  ... {i}/{len(targets)} | UP={updated} NO_IMG={no_img} FAIL={failed} elapsed={elapsed}s",
                  flush=True)

    db.commit()
    db.close()
    print(f"\n=== 完了 ===")
    print(f"  UPDATE:  {updated}")
    print(f"  NO IMG:  {no_img}")
    print(f"  FAIL:    {failed}")


if __name__ == "__main__":
    main()
