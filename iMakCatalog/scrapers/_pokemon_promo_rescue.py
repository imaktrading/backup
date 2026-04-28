#!/usr/bin/env python3
"""Pokemon promo card 救済スクリプト (one-off).

`cardID-XXXX` fallback で投入された 3434 件を再 fetch + 再 parse + DB upsert.
旧 parser で促成番号 (e.g., '001/SM-P') を取れなかった records を救う.

実行:
    python scrapers/_pokemon_promo_rescue.py --dry-run    # 1件試走
    python scrapers/_pokemon_promo_rescue.py              # 本走 (~85 分)
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import api  # noqa: E402

# Reuse pokemon_tcg's parser + HTTP
sys.path.insert(0, str(Path(__file__).resolve().parent))
import pokemon_tcg as pt  # noqa: E402


def find_cardid_fallback_records() -> list[tuple[int, str]]:
    """DB から cardID-XXXX 形式の records を抽出. Returns [(db_id, card_id), ...]"""
    conn = sqlite3.connect(api._DB_PATH)
    rows = conn.execute(
        "SELECT id, product_id FROM products "
        "WHERE category='pokemon_tcg' AND product_id LIKE 'cardID-%'"
    ).fetchall()
    conn.close()
    out: list[tuple[int, str]] = []
    for db_id, pid in rows:
        m = re.match(r"^cardID-(\d+)$", pid)
        if m:
            out.append((db_id, m.group(1)))
    return out


def rescue_one(db_id: int, card_id: str, dry_run: bool = False) -> dict:
    """1件の cardID-XXXX を再 fetch + 再 parse + DB 更新."""
    # キャッシュ削除して再 fetch を強制
    cache_path = pt.CACHE_DIR / f"detail_{card_id}.json"
    if cache_path.exists():
        cache_path.unlink()

    detail = pt.get_detail(card_id)
    if not detail:
        return {"status": "fetch_failed", "card_id": card_id}

    new_pid = pt.derive_product_id(detail)
    if not new_pid:
        return {"status": "no_pid", "card_id": card_id}
    if new_pid.startswith("cardID-"):
        # まだ番号が取れない (本物の番号無しカード)
        return {"status": "still_cardid", "card_id": card_id, "name": detail.get("name", "")}

    # 古い cardID-XXX record を削除して、新 product_id で upsert
    if dry_run:
        print(f"  [DRY] {card_id} → {new_pid} ({detail.get('name', '')})")
        return {"status": "would_update", "card_id": card_id, "new_pid": new_pid}

    conn = sqlite3.connect(api._DB_PATH)
    try:
        # Check if new_pid already exists (collision)
        existing = conn.execute(
            "SELECT id FROM products WHERE category='pokemon_tcg' AND product_id=?",
            (new_pid,),
        ).fetchone()
        if existing and existing[0] != db_id:
            # Collision: new_pid 既に別 record ある → 古い cardID record だけ削除
            conn.execute("DELETE FROM products WHERE id=?", (db_id,))
            conn.commit()
            return {"status": "merged_collision", "card_id": card_id, "new_pid": new_pid}
        # 古い row を削除 (UNIQUE 制約回避のため) → upsert で新 pid 投入
        conn.execute("DELETE FROM products WHERE id=?", (db_id,))
        conn.commit()
    finally:
        conn.close()

    # pt.build_and_upsert を使って新 product_id で投入
    pt.build_and_upsert(card_id, dry_run=False)
    return {"status": "updated", "card_id": card_id, "new_pid": new_pid,
            "name": detail.get("name", "")}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true", help="DB 書き込まず先頭 5 件だけ確認")
    p.add_argument("--limit", type=int, help="先頭 N 件のみ処理")
    args = p.parse_args()

    targets = find_cardid_fallback_records()
    print(f"Target cardID-XXXX records: {len(targets)}")

    if args.dry_run:
        targets = targets[:5]
        print(f"DRY RUN: 先頭 {len(targets)} 件")
    elif args.limit:
        targets = targets[: args.limit]
        print(f"LIMIT: 先頭 {len(targets)} 件")

    counts = {"updated": 0, "still_cardid": 0, "merged_collision": 0,
              "fetch_failed": 0, "no_pid": 0, "would_update": 0}
    for i, (db_id, card_id) in enumerate(targets):
        try:
            r = rescue_one(db_id, card_id, dry_run=args.dry_run)
            counts[r["status"]] = counts.get(r["status"], 0) + 1
        except Exception as e:
            print(f"  ⚠️ {card_id}: {e}")
            counts.setdefault("error", 0)
            counts["error"] += 1
        if (i + 1) % 50 == 0:
            print(f"  ... {i+1}/{len(targets)} processed: {counts}", flush=True)

    print(f"\n=== 完了 ===")
    print(json.dumps(counts, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
