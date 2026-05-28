"""DON-EVENT-003 image_phash 上書き (= 手動 mapping、 cert 146160792 = 1ST Anniversary Event).

依頼: 2026-05-28_catalog_614_marco_anniversary_psa_hash_phase_a.md

背景:
  cert 146160792 (= HIGH 614、 ONE PIECE JAPANESE PROMOS / DON!! CARD) は
  brand 'PROMOS' で set_code 抽出不能 → 自動 mapping fail (= 5/28 10:25 PSA cache 移行で skip)。

  ユーザー画像判定 (= 5/28 11:50、 HTML viewer 経由 全 265 件 thumbnail 比較):
  - cert 146160792 cert image = catalog DON-EVENT-003 (= ストレージボックス×ドン!!カードセット
    内の dancing Luffy silhouette variant) と一致 → 紐付け確定

cross-validation (= 完了後 visual verify):
  - PSA cert image: "2023 ONE PIECE JP DON!! CARD 1ST ANNIVERSARY EVENT" PSA 146160792 GEM MT 10
    dancing Luffy silhouette + "ドン、ドットットッ♪" 文字
  - DON-EVENT-003 PDF 切出: 同 dancing Luffy silhouette + 同文字 ✓

= ユーザー判定 + 視覚 verify 両方 OK、 教師データ初回投入。

hamming PSA vs PDF (= 同 entry 旧): 16 (= source 不整合 noise 範囲内)
"""
from __future__ import annotations

import json
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

DB = str(api._DB_PATH)
NOW = datetime.now().isoformat()
CACHE_FILE = Path("C:/dev/iMak/iMakeBayAPI/cache/psa_certs/146160792.json")
TARGET_PRODUCT_ID = "DON-EVENT-003"
TARGET_CERT = "146160792"


def main():
    import imagehash
    from PIL import Image
    import requests
    import io

    # 1. cache から CardImageUrl 取得
    meta = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    image_url = meta["CardImageUrl"]
    print(f"cert {TARGET_CERT} CardImageUrl: {image_url}")

    # 2. image fetch + phash
    resp = requests.get(image_url, timeout=15)
    if resp.status_code != 200:
        print(f"  FAIL: HTTP {resp.status_code}")
        return
    img = Image.open(io.BytesIO(resp.content))
    new_phash = str(imagehash.phash(img))
    print(f"  PSA phash: {new_phash}")

    # 3. catalog UPDATE (= DON-EVENT-003 variants.default 上書き)
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    r = db.execute(
        "SELECT variants FROM products WHERE category='one_piece_tcg' AND product_id=?",
        (TARGET_PRODUCT_ID,),
    ).fetchone()
    if not r:
        print(f"  FAIL: {TARGET_PRODUCT_ID} 既存 entry なし")
        return

    variants = json.loads(r["variants"]) if r["variants"] else {}
    old_phash = variants.get("default", {}).get("image_phash")
    print(f"  PDF phash (旧): {old_phash}")

    # hamming verify
    if old_phash:
        new_h = imagehash.hex_to_hash(new_phash)
        old_h = imagehash.hex_to_hash(old_phash)
        print(f"  hamming PSA vs PDF (= 同 entry): {new_h - old_h}")

    variants["default"] = variants.get("default", {})
    # rollback 用保存: 既に image_phash_pdf_v1 がある場合は上書きしない (= 冪等性確保)
    if old_phash and "image_phash_pdf_v1" not in variants["default"]:
        variants["default"]["image_phash_pdf_v1"] = old_phash
    variants["default"]["image_phash"] = new_phash
    variants["default"]["image_phash_source"] = "psa_cert_holder_2026-05-28"
    variants["default"]["image_phash_cert"] = TARGET_CERT
    variants["default"]["mapping_method"] = "user_visual_judgment_html_viewer"

    db.execute(
        "UPDATE products SET variants=?, updated_at=? "
        "WHERE category='one_piece_tcg' AND product_id=?",
        (json.dumps(variants, ensure_ascii=False), NOW, TARGET_PRODUCT_ID),
    )
    db.commit()
    db.close()
    print(f"  UPDATE: {TARGET_PRODUCT_ID} ← cert {TARGET_CERT}")


if __name__ == "__main__":
    main()
