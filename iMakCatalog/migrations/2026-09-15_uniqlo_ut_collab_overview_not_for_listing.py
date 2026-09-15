"""コラボ紹介記事を1行にした UT 3行に not_for_listing を付ける — 2026-09-15

窓口 GO: requests/2026-09-15_fashion_press_rows_flag_go.md
(元: 2026-09-14_fashion_press_rows_without_flags.md / 回答 _response.md)

`is_collab_overview=true` の3行 (FP-102598 / FP-143930 / FP-143792、2026-05-06 作成) は品番ではなく
出品に使えない。9/13 に柄の記録 (`data_level=fp_design`) へ `not_for_listing` を付けた時に対象外にしていて、
印が漏れていた。今後の除外は `not_for_listing` の1本で済むようにする。

★`FP-` で始まる DBSCG のカード番号 (271件) は触らない。category='uniqlo_ut' と印で絞る。

実行:
    python migrations/2026-09-15_uniqlo_ut_collab_overview_not_for_listing.py            # dry-run
    python migrations/2026-09-15_uniqlo_ut_collab_overview_not_for_listing.py --commit
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime

DB = "C:/dev/iMak_data/catalog/products.sqlite"
EXPECTED = {"FP-102598", "FP-143930", "FP-143792"}

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def main(commit: bool) -> None:
    db = sqlite3.connect(DB, timeout=120)
    rows = db.execute("SELECT id, product_id, specs FROM products WHERE category='uniqlo_ut' "
                      "AND json_extract(specs,'$.is_collab_overview')").fetchall()
    found = {pid for _, pid, _ in rows}
    if found != EXPECTED:
        print(f"対象が想定と違うので書かない: {sorted(found)}")
        return
    now = datetime.now().isoformat(timespec="seconds")
    todo = [(rid, pid, json.loads(sp)) for rid, pid, sp in rows if not json.loads(sp).get("not_for_listing")]
    if commit:
        for rid, pid, s in todo:
            s["not_for_listing"] = True
            s["not_for_listing_reason"] = "コラボ紹介記事を1行にした行。品番ではないので出品に使えない"
            s["not_for_listing_at"] = now
            db.execute("UPDATE products SET specs=?, updated_at=? WHERE id=?",
                       (json.dumps(s, ensure_ascii=False), now, rid))
        db.commit()
    left = db.execute("SELECT count(*) FROM products WHERE category='uniqlo_ut' "
                      "AND json_extract(specs,'$.is_collab_overview') "
                      "AND NOT coalesce(json_extract(specs,'$.not_for_listing'),0)").fetchone()[0]
    total = db.execute("SELECT count(*) FROM products WHERE category='uniqlo_ut' "
                       "AND json_extract(specs,'$.not_for_listing')").fetchone()[0]
    print(f"対象 {len(todo)}行 / 印なしの紹介行 残り {left} / not_for_listing=true (uniqlo_ut) {total}件 / "
          f"{'commit' if commit else 'dry-run'}")


if __name__ == "__main__":
    main("--commit" in sys.argv)
