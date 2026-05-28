"""DON image_phash 再投入 (= iMakeBayAPI cache CardImageUrl 経由 PSA 公式画像).

依頼: 2026-05-28_catalog_image_phash_from_psa_cache_REPLACE.md

目的:
  旧 PDF 切出画像 (= bandai 公式 PDF) は mercari 出品画像 (= PSA holder 越し撮影)
  と source 不整合で hamming 16-30 (= THRESHOLD=10 超過)。
  PSA cert page 画像 (= iMakeBayAPI cache CardImageUrl) は **同 PSA holder 越し** source、
  hamming 大幅減見込。

flow:
  1. C:/dev/iMak/iMakeBayAPI/cache/psa_certs/*.json を scan
  2. Subject に 'DON' 含む cert 抽出
  3. lookup_don(brand, subject) で catalog variant 一意特定
  4. tie / 0 件 → skip (= 別 phase 手動 mapping)
  5. CardImageUrl から画像 download → imagehash.phash
  6. catalog products.variants.default.image_phash 上書き
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
from integrations import psa_to_csv  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

DB = str(api._DB_PATH)
NOW = datetime.now().isoformat()
PSA_CACHE_DIR = Path("C:/dev/iMak/iMakeBayAPI/cache/psa_certs")
FETCH_TIMEOUT = 15


def compute_phash_from_url(image_url: str) -> str | None:
    """画像 URL → 64bit phash hex. fail-closed."""
    try:
        import imagehash  # type: ignore
        from PIL import Image  # type: ignore
        import requests  # type: ignore
        import io
        resp = requests.get(image_url, timeout=FETCH_TIMEOUT)
        if resp.status_code != 200:
            return None
        img = Image.open(io.BytesIO(resp.content))
        return str(imagehash.phash(img))
    except Exception:
        return None


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--probe", action="store_true", help="DON cert list 抽出のみ")
    p.add_argument("--dry-run", action="store_true", help="hash 計算するが DB 触らず")
    p.add_argument("--limit", type=int, help="先頭 N 件のみ")
    args = p.parse_args()

    # 1. cache scan + DON 抽出
    don_certs = []
    cert_files = sorted(PSA_CACHE_DIR.glob("*.json"))
    print(f"cache total: {len(cert_files)} files")
    for f in cert_files:
        try:
            meta = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        subject = (meta.get("Subject") or "").upper()
        brand = (meta.get("Brand") or "").upper()
        url = meta.get("CardImageUrl")
        if "DON" not in subject:
            continue
        if not url:
            continue
        don_certs.append({
            "cert": f.stem,
            "brand": brand,
            "subject": subject,
            "image_url": url,
        })

    print(f"DON cert (subject 'DON' + CardImageUrl 有): {len(don_certs)}")

    if args.probe:
        for c in don_certs:
            print(f"  {c['cert']:12s} brand={c['brand'][:50]!r}")
            print(f"               subject={c['subject']!r}")
            print(f"               url={c['image_url']}")
        return

    if args.limit:
        don_certs = don_certs[: args.limit]

    # 2. cert → catalog variant 紐付け
    # 戦略 A: lookup_don で一意特定可能 → そのまま採用
    # 戦略 B: tie の場合、 brand から set_code 絞込 → 各候補 PDF hash と PSA hash の
    #         hamming 比較 → 最近接 variant を採用 (= source 不整合下でも相対 ranking で識別)
    print()
    print("=== cert → catalog variant 紐付け ===")
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    mappings = []
    for c in don_certs:
        # 戦略 A: lookup_don で一意特定
        record = psa_to_csv.lookup_don(c["brand"], c["subject"], verbose=False)
        if record:
            mappings.append({
                **c,
                "product_id": record["product_id"],
                "method": "lookup_don",
            })
            print(f"  cert {c['cert']} → {record['product_id']} (= lookup_don 一意特定)")
            continue

        # 戦略 B: brand から set_code 抽出 → set_code 内候補で PSA hash 最近接 PDF hash 探索
        import re
        m = re.search(r"\b(OP|ST|EB|PRB)\s*-?\s*(\d+)\b", c["brand"])
        set_code = f"{m.group(1)}{m.group(2)}" if m else None
        if not set_code:
            print(f"  cert {c['cert']} → brand から set_code 抽出不能、 SKIP (= 別 phase 手動 mapping)")
            continue

        # 候補絞込
        rows = db.execute(
            "SELECT product_id, variants FROM products WHERE category='one_piece_tcg' "
            "AND product_id LIKE ?",
            (f"DON-{set_code}-%",),
        ).fetchall()
        if not rows:
            print(f"  cert {c['cert']} → DON-{set_code}-* 候補なし、 SKIP")
            continue

        # PSA hash 計算 (= 後で reuse するため cert dict に格納)
        psa_phash = compute_phash_from_url(c["image_url"])
        if not psa_phash:
            print(f"  cert {c['cert']} → PSA image 取得 fail、 SKIP")
            continue
        c["psa_phash_precomputed"] = psa_phash

        # 各候補 PDF hash と PSA hash の hamming 比較 (= 最近接 = 該当 variant 仮説)
        import imagehash
        psa_hash_obj = imagehash.hex_to_hash(psa_phash)
        ranks = []
        for r in rows:
            try:
                variants = json.loads(r["variants"]) if r["variants"] else {}
                pdf_phash = variants.get("default", {}).get("image_phash")
                if not pdf_phash:
                    continue
                pdf_hash_obj = imagehash.hex_to_hash(pdf_phash)
                dist = psa_hash_obj - pdf_hash_obj
                ranks.append((r["product_id"], dist, pdf_phash))
            except Exception:
                continue
        ranks.sort(key=lambda x: x[1])
        if ranks:
            best_pid, best_dist, _ = ranks[0]
            mappings.append({
                **c,
                "product_id": best_pid,
                "method": f"pdf_hamming_min={best_dist}",
            })
            print(f"  cert {c['cert']} → {best_pid} (= PDF hash 最近接 hamming={best_dist}、 候補 {len(ranks)})")
            for pid, dist, _ in ranks[:3]:
                print(f"      ranking: {pid} hamming={dist}")
        else:
            print(f"  cert {c['cert']} → DON-{set_code}-* で hash 比較不能、 SKIP")
    print(f"\n紐付け成功: {len(mappings)}")
    print(f"紐付け失敗: {len(don_certs) - len(mappings)}")
    db.close()

    # 3. image download + hash + catalog 上書き
    print()
    print("=== hash 計算 + catalog 上書き ===")
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    updated, failed = 0, 0
    for m in mappings:
        # 戦略 B で既に hash 計算済なら reuse、 未なら計算
        phash = m.get("psa_phash_precomputed") or compute_phash_from_url(m["image_url"])
        if not phash:
            print(f"  FAIL: cert {m['cert']} ({m['product_id']}) hash 取得失敗")
            failed += 1
            continue

        if args.dry_run:
            print(f"  [DRY] {m['cert']} → {m['product_id']} phash={phash}")
            updated += 1
            continue

        # variants.default.image_phash 上書き
        row = db.execute(
            "SELECT variants FROM products WHERE category='one_piece_tcg' AND product_id=?",
            (m["product_id"],),
        ).fetchone()
        if not row:
            print(f"  WARN: {m['product_id']} 既存 entry なし SKIP")
            continue
        try:
            variants = json.loads(row["variants"]) if row["variants"] else {}
        except Exception:
            variants = {}
        # 旧 PDF 切出 phash を保存しつつ default を上書き (= 冪等性確保、 既存 pdf_v1 は keep)
        if "default" in variants and isinstance(variants["default"], dict):
            old_phash = variants["default"].get("image_phash")
            if old_phash and "image_phash_pdf_v1" not in variants["default"]:
                variants["default"]["image_phash_pdf_v1"] = old_phash  # rollback 用 (= 初回のみ)
        variants["default"] = variants.get("default", {})
        variants["default"]["image_phash"] = phash
        variants["default"]["image_phash_source"] = "psa_cert_holder_2026-05-28"
        variants["default"]["image_phash_cert"] = m["cert"]

        db.execute(
            "UPDATE products SET variants=?, updated_at=? "
            "WHERE category='one_piece_tcg' AND product_id=?",
            (json.dumps(variants, ensure_ascii=False), NOW, m["product_id"]),
        )
        print(f"  UPDATE: {m['cert']} → {m['product_id']} phash={phash}")
        updated += 1

    if not args.dry_run:
        db.commit()
    db.close()

    print()
    print("=== 完了 ===")
    print(f"  UPDATE: {updated}")
    print(f"  FAIL:   {failed}")
    print(f"  total:  {len(mappings)}")


if __name__ == "__main__":
    main()
