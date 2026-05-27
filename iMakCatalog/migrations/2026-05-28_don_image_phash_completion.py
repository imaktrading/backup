"""DON 265 件 画像切出 + image_phash 投入 (= ③ Phase C 完走 DON 編).

依頼: 2026-05-28_catalog_don_image_phash_completion.md

設計:
  - source: 既存 PDF page sample PNG (= `_don_pdf_samples/page_NN.png`、 5/27 Vision OCR 時保存済)
  - Option C 採用: 既存 PNG 流用 + 3x3 grid 切出 (= page 1-29) + 3+1 layout (= page 30)
  - 切出画像を `_don_images/{product_id}.png` に保存
  - products.images + variants JSON ({"default": {"image_phash": ...}}) 投入
  - 重複くん `dedupe/image_hash.py::compute_phash()` と同 logic (= imagehash 4.3.2 + Pillow 12.2.0)

実行:
    python migrations/2026-05-28_don_image_phash_completion.py --probe  # 件数集計のみ
    python migrations/2026-05-28_don_image_phash_completion.py --limit 5  # 先頭 5 件 sample
    python migrations/2026-05-28_don_image_phash_completion.py          # 本走 (= 265 件)
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
PDF_SAMPLES_DIR = Path("C:/dev/iMak_data/catalog/_don_pdf_samples")
OUT_DIR = Path("C:/dev/iMak_data/catalog/_don_images")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# PDF page 寸法 (= 5/27 pymupdf 2x scale で生成)
PAGE_W = 1191
PAGE_H = 1684

# 3x3 grid bounds (= pages 1-29)
GRID_COLS = [(75, 422), (422, 769), (769, 1116)]
GRID_ROWS = [(195, 660), (660, 1125), (1125, 1590)]

# Page 30 特殊 (= 3+1 layout: row 1 = 3 cards、 row 2 = 1 card col 0 のみ)
PAGE30_POS_TO_CELL = {
    1: (0, 0),  # row 0 col 0 = ブースターパック 神の島の冒険 [OP-15]
    2: (0, 1),  # row 0 col 1 = ブースターパック 決断の刻 [OP-16]
    3: (0, 2),  # row 0 col 2 = ブースターパック 決断の刻 [OP-16] variant
    4: (1, 0),  # row 1 col 0 = イベント配布
}


def pos_to_cell(page: int, pos: int) -> tuple[int, int]:
    """page-position (= 1-9) → (row, col)."""
    if page == 30:
        return PAGE30_POS_TO_CELL[pos]
    # 1-9 → row = (pos-1) // 3, col = (pos-1) % 3
    return ((pos - 1) // 3, (pos - 1) % 3)


def get_card_bbox(page: int, pos: int) -> tuple[int, int, int, int]:
    """page-position → (x1, y1, x2, y2)."""
    row, col = pos_to_cell(page, pos)
    x1, x2 = GRID_COLS[col]
    y1, y2 = GRID_ROWS[row]
    return (x1, y1, x2, y2)


def load_page_pos_to_pid() -> dict[tuple[int, int], str]:
    """catalog products から (page, pos) → product_id mapping 再構築.

    DON entries の specs.page_in_pdf + specs.position_in_page から再構築。
    """
    mapping = {}
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    try:
        for r in db.execute(
            "SELECT product_id, specs FROM products "
            "WHERE category='one_piece_tcg' AND product_id LIKE 'DON-%'"
        ):
            try:
                specs = json.loads(r["specs"])
            except Exception:
                continue
            page = specs.get("page_in_pdf")
            pos = specs.get("position_in_page")
            if page is None or pos is None:
                continue
            mapping[(page, pos)] = r["product_id"]
    finally:
        db.close()
    return mapping


def crop_and_save(page: int, pos: int, product_id: str) -> Path | None:
    """page PNG から該当 card 切出 + 保存. 失敗時 None."""
    page_png = PDF_SAMPLES_DIR / f"page_{page:02d}.png"
    if not page_png.exists():
        return None

    from PIL import Image  # type: ignore
    img = Image.open(page_png)
    bbox = get_card_bbox(page, pos)
    crop = img.crop(bbox)
    out = OUT_DIR / f"{product_id}.png"
    crop.save(out)
    return out


def compute_phash_from_file(image_path: Path) -> str | None:
    """画像 file → 64bit phash hex. fail-closed."""
    try:
        import imagehash  # type: ignore
        from PIL import Image  # type: ignore
        img = Image.open(image_path)
        return str(imagehash.phash(img))
    except Exception:
        return None


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--probe", action="store_true", help="件数集計のみ")
    p.add_argument("--limit", type=int, help="先頭 N 件のみ処理")
    args = p.parse_args()

    mapping = load_page_pos_to_pid()
    print(f"DON page-position 対象: {len(mapping)} 件")

    if args.probe:
        # 既存 _don_images/ 件数
        existing = list(OUT_DIR.glob("DON-*.png"))
        print(f"既存切出画像: {len(existing)}")
        # variants 投入済
        n_with_hash = 0
        db = sqlite3.connect(DB)
        for (page, pos), pid in mapping.items():
            r = db.execute(
                "SELECT variants FROM products WHERE category='one_piece_tcg' AND product_id=?",
                (pid,),
            ).fetchone()
            if r and r[0] and "image_phash" in r[0]:
                n_with_hash += 1
        db.close()
        print(f"image_phash 投入済: {n_with_hash}")
        return

    targets = sorted(mapping.items(), key=lambda kv: (kv[0][0], kv[0][1]))
    if args.limit:
        targets = targets[: args.limit]
    print(f"target: {len(targets)} 件")

    db = sqlite3.connect(DB)
    updated, failed = 0, 0
    started_at = time.time()
    for i, ((page, pos), pid) in enumerate(targets, start=1):
        try:
            out_path = crop_and_save(page, pos, pid)
            if not out_path:
                failed += 1
                continue
            phash = compute_phash_from_file(out_path)
            if not phash:
                failed += 1
                continue

            # variants JSON に default key で image_phash 投入
            variants = {"default": {"image_phash": phash}}
            # images 列に local path 投入
            images = [str(out_path).replace("\\", "/")]
            db.execute(
                "UPDATE products SET images=?, variants=?, updated_at=? "
                "WHERE category='one_piece_tcg' AND product_id=?",
                (
                    json.dumps(images, ensure_ascii=False),
                    json.dumps(variants, ensure_ascii=False),
                    NOW,
                    pid,
                ),
            )
            updated += 1
        except Exception as e:
            print(f"  ⚠️ {pid}: {e}")
            failed += 1

        if i % 50 == 0:
            db.commit()
            elapsed = int(time.time() - started_at)
            print(f"  ... {i}/{len(targets)} done | OK={updated} FAIL={failed} elapsed={elapsed}s",
                  flush=True)

    db.commit()
    db.close()

    elapsed = int(time.time() - started_at)
    print()
    print(f"=== 完了 ===")
    print(f"  UPDATE: {updated}")
    print(f"  FAIL:   {failed}")
    print(f"  elapsed: {elapsed} sec")


if __name__ == "__main__":
    main()
