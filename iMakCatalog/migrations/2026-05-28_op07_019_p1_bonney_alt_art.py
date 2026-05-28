"""OP07-019_p1 (= Jewelry Bonney Alternate Art) 新規 catalog 投入.

依頼: 2026-05-28_catalog_add_jewelry_bonney_op07_019_alt.md

背景:
  cert 91894036 (= ONE PIECE JAPANESE OP07 / JEWELRY BONNEY ALTERNATE ART) で
  post_psa_review HTML viewer 30 候補 全 NONE 判定 (= 該当 entry なし)。
  既存 OP07-019 5 variants:
    - OP07-019 (base, OP07 booster)
    - OP07-019_p (1st parallel, OP07 booster)
    - OP07-019_ST24 (ST-24 starter)
    - OP07-019_EB02_LF (EB-02 Anime 25th)
    - OP07-019_P (Promotion)
  cert label "OP07-ALTERNATE ART" は **既存 _p とは別 composition** (= visual verify 済)。
  Bandai TCG+ DB に該当 URL なし (= tournament/event 限定で main DB 未登録想定)。
  PSA cert holder image を catalog image source として採用。

product_id 命名規則:
  既存 _p (lowercase) = 1st parallel、 本依頼で `_p1` = 2nd parallel (= numbered)
  OPCG 内 既存 _PRB02_p1 / _PRB02_p2 等の precedent あり (= 番号 parallel pattern)
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

# === 新規 entry 定義 ===
NEW_PID = "OP07-019_p1"
CERT = "91894036"
CACHE_FILE = Path(f"C:/dev/iMak/iMakeBayAPI/cache/psa_certs/{CERT}.json")
BASE_PID = "OP07-019"  # = base から specs 継承


def main():
    import imagehash
    from PIL import Image
    import requests
    import io

    # 1. cache から CardImageUrl
    meta = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    image_url = meta["CardImageUrl"]
    print(f"cert {CERT} cache:")
    print(f"  brand={meta.get('Brand')!r}")
    print(f"  subject={meta.get('Subject')!r}")
    print(f"  CardImageUrl={image_url}")

    # 2. PSA image download + phash
    resp = requests.get(image_url, timeout=15)
    if resp.status_code != 200:
        print(f"  FAIL: HTTP {resp.status_code}")
        return
    img = Image.open(io.BytesIO(resp.content))
    phash = str(imagehash.phash(img))
    print(f"  PSA phash: {phash}")

    # 3. base OP07-019 から specs 継承
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    base = db.execute(
        "SELECT * FROM products WHERE category='one_piece_tcg' AND product_id=?",
        (BASE_PID,),
    ).fetchone()
    if not base:
        print(f"  FAIL: base entry {BASE_PID} 不在")
        return

    base_specs = json.loads(base["specs"]) if base["specs"] else {}
    new_specs = dict(base_specs)  # shallow copy
    new_specs["variant"] = "Alternate Art"
    new_specs["variant_source"] = f"PSA cert {CERT}"
    new_specs["base_product_id"] = BASE_PID

    # variants JSON (= PSA cert holder image_phash)
    variants = {
        "default": {
            "image_phash": phash,
            "image_phash_source": "psa_cert_holder_2026-05-28",
            "image_phash_cert": CERT,
            "mapping_method": "new_entry_psa_label_visual_verify",
        }
    }

    # 既存重複確認
    existing = db.execute(
        "SELECT id FROM products WHERE category='one_piece_tcg' AND product_id=?",
        (NEW_PID,),
    ).fetchone()
    if existing:
        print(f"  WARN: {NEW_PID} 既存 entry あり、 UPDATE で対応")
        db.execute(
            "UPDATE products SET specs=?, variants=?, images=?, updated_at=? "
            "WHERE category='one_piece_tcg' AND product_id=?",
            (
                json.dumps(new_specs, ensure_ascii=False),
                json.dumps(variants, ensure_ascii=False),
                json.dumps([image_url], ensure_ascii=False),
                NOW,
                NEW_PID,
            ),
        )
    else:
        # INSERT
        db.execute(
            "INSERT INTO products "
            "(category, product_id, name, name_jp, name_en, set_name, set_name_official, "
            " card_set_id, language, specs, images, variants, source, source_url, "
            " created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "one_piece_tcg",
                NEW_PID,
                base["name"] or "Jewelry Bonney",
                base["name_jp"] or "ジュエリー・ボニー",
                base["name_en"] if "name_en" in base.keys() else "Jewelry Bonney",
                base["set_name"],
                base["set_name_official"],
                base["card_set_id"] if "card_set_id" in base.keys() else None,
                base["language"] if "language" in base.keys() else "JA",
                json.dumps(new_specs, ensure_ascii=False),
                json.dumps([image_url], ensure_ascii=False),
                json.dumps(variants, ensure_ascii=False),
                "psa_cert_91894036",
                f"https://www.psacard.com/ja-JP/cert/{CERT}/psa",
                NOW,
                NOW,
            ),
        )
        print(f"  INSERT: {NEW_PID}")

    db.commit()
    db.close()
    print(f"\n=== 完了 ===")
    print(f"  product_id: {NEW_PID}")
    print(f"  phash: {phash}")
    print(f"  image: {image_url}")


if __name__ == "__main__":
    main()
