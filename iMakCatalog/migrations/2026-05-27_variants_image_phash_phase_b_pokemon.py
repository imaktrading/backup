"""variant Phase B (= image_phash 投入) — Pokemon 4,921 件.

依頼: 2026-05-27_catalog_variant_image_phash_phase_b.md

Phase A.1 投入済 variants JSON に `image_phash` field 追加 (= 64bit phash hex 16 桁).
重複くん `dedupe/image_hash.py::compute_phash()` と同 logic (= imagehash.phash) 利用、
hash 互換性は POC で確認済 (= 同 image_url → 同 hash 値).

実行:
    python migrations/2026-05-27_variants_image_phash_phase_b_pokemon.py --probe   # 件数集計のみ
    python migrations/2026-05-27_variants_image_phash_phase_b_pokemon.py --limit 50  # 先頭 50 件 sample
    python migrations/2026-05-27_variants_image_phash_phase_b_pokemon.py            # 本走
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
import api  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

DB = str(api._DB_PATH)
NOW = datetime.now().isoformat()
FETCH_TIMEOUT = 15
POLITE_DELAY = 0.3  # rate limit 配慮 (= pokemon-card.com)


def _import_libs():
    """遅延 import (= imagehash 不在環境への配慮)."""
    import imagehash  # type: ignore
    from PIL import Image  # type: ignore
    import requests  # type: ignore
    return imagehash, Image, requests


def compute_phash(image_url: str, imagehash_mod, Image, requests_mod) -> str | None:
    """画像 URL → 64bit phash hex (= 16 文字). fail-closed (= 失敗 None)."""
    try:
        resp = requests_mod.get(image_url, timeout=FETCH_TIMEOUT)
        if resp.status_code != 200:
            return None
        import io
        img = Image.open(io.BytesIO(resp.content))
        return str(imagehash_mod.phash(img))
    except Exception:
        return None


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--probe", action="store_true", help="件数集計のみ")
    p.add_argument("--limit", type=int, help="先頭 N 件のみ処理")
    p.add_argument("--start", type=int, default=0, help="先頭 N skip (= resume 用)")
    args = p.parse_args()

    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row

    rows = db.execute(
        "SELECT id, product_id, images, variants FROM products "
        "WHERE category='pokemon_tcg' AND variants IS NOT NULL "
        "AND images IS NOT NULL AND images != '[]' "
        "ORDER BY id"
    ).fetchall()
    print(f"対象 (variants + images 保有): {len(rows)}")

    if args.probe:
        # image_phash 既投入 entry 計数
        already = 0
        for r in rows:
            try:
                v = json.loads(r["variants"])
                for code, meta in v.items():
                    if isinstance(meta, dict) and meta.get("image_phash"):
                        already += 1
                        break
            except Exception:
                pass
        print(f"  image_phash 既投入: {already}")
        print(f"  未投入: {len(rows) - already}")
        db.close()
        return

    target_rows = rows[args.start: args.start + args.limit if args.limit else len(rows)]
    print(f"target: {len(target_rows)} 件 (range {args.start}..)")

    imagehash_mod, Image, requests_mod = _import_libs()

    updated, failed = 0, 0
    started_at = time.time()
    for i, r in enumerate(target_rows, start=1):
        pid = r["product_id"]
        try:
            imgs = json.loads(r["images"])
            variants = json.loads(r["variants"])
        except Exception:
            failed += 1
            continue
        if not imgs:
            failed += 1
            continue
        image_url = imgs[0]
        phash = compute_phash(image_url, imagehash_mod, Image, requests_mod)
        if not phash:
            failed += 1
            time.sleep(POLITE_DELAY)
            continue

        # 全 variant entry に同 image_phash 設定 (= 1 product_id 1 image、 multi-variant でも共有)
        for code, meta in variants.items():
            if isinstance(meta, dict):
                meta["image_phash"] = phash

        db.execute(
            "UPDATE products SET variants=?, updated_at=? WHERE id=?",
            (json.dumps(variants, ensure_ascii=False), NOW, r["id"]),
        )
        updated += 1
        time.sleep(POLITE_DELAY)

        if i % 100 == 0:
            db.commit()
            elapsed = int(time.time() - started_at)
            eta = int(elapsed / i * (len(target_rows) - i))
            print(f"    ... {i}/{len(target_rows)} done | OK={updated} FAIL={failed} "
                  f"elapsed={elapsed}s ETA={eta}s", flush=True)

    db.commit()
    db.close()

    elapsed = int(time.time() - started_at)
    print()
    print(f"=== 完了 ===")
    print(f"  UPDATE: {updated}")
    print(f"  FAIL:   {failed}")
    print(f"  total:  {len(target_rows)}")
    print(f"  elapsed: {elapsed} sec ({elapsed/60:.1f} min)")


if __name__ == "__main__":
    main()
