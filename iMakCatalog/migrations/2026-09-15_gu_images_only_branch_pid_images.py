"""GU の画像だけの行のうち、枝番の品番 6行に付けた「-000 の商品の画像」を直す — 2026-09-15

`scrapers/gu_graphic_discover.py` の初回は画像の置き場所を品番の数字6桁で探していた。
GU は枝番ごとに置き場所が別 (E361361-001 → `imagesgoods/361361001/`) なので、
E356602-001 / -002 / -003 等に **E356602-000 の画像**が付いた (同日修正済み)。

対象: category='gu' / source='gu_reviews_cdn' / 品番の枝番が 000 以外。
直した道具 (`images_of`) で取り直し、
  見つかった → 画像を差し替える
  見つからない → **行を消す** (正しい画像も値も無い行は持たない。出品しない印の行なので出品には影響しない)

実行:
    python migrations/2026-09-15_gu_images_only_branch_pid_images.py            # dry-run
    python migrations/2026-09-15_gu_images_only_branch_pid_images.py --commit
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "scrapers")]
import gu_graphic_discover as G  # noqa: E402

DB = "C:/dev/iMak_data/catalog/products.sqlite"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def main(commit: bool) -> None:
    db = sqlite3.connect(DB, timeout=120)
    rows = [r for r in db.execute("SELECT id, product_id, name, specs FROM products "
                                  "WHERE category='gu' AND source='gu_reviews_cdn'").fetchall()
            if not r[1].endswith("-000")]
    now = datetime.now().isoformat(timespec="seconds")
    fixed = dropped = 0
    for rid, pid, name, sp in rows:
        imgs = G.images_of(pid)
        folder = pid[1:7] + pid[8:11]
        assert all(f"/{folder}/" in u for u in imgs), (pid, imgs[:2])
        print(f"  {pid} {name[:30]}: 正しい置き場所の画像 {len(imgs)}枚 → {'差し替え' if imgs else '行を消す'}")
        if not commit:
            continue
        if imgs:
            s = json.loads(sp or "{}")
            s["image_urls"] = imgs
            s["images_fixed_at"] = now
            db.execute("UPDATE products SET images=?, specs=?, updated_at=? WHERE id=?",
                       (json.dumps(imgs), json.dumps(s, ensure_ascii=False), now, rid))
            fixed += 1
        else:
            db.execute("DELETE FROM products WHERE id=?", (rid,))
            dropped += 1
    if commit:
        db.commit()
    left = sum(1 for (pid, im) in db.execute(
        "SELECT product_id, images FROM products WHERE category='gu' AND source='gu_reviews_cdn'")
        if not pid.endswith("-000") and any(f"/{pid[1:7]}/" in u for u in json.loads(im or "[]")))
    print(f"対象 {len(rows)}行 / 差し替え {fixed} / 削除 {dropped} / 誤った画像の残り {left}行 / "
          f"{'commit' if commit else 'dry-run'}")


if __name__ == "__main__":
    main("--commit" in sys.argv)
