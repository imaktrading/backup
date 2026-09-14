"""サイズページ取得の初回走行で入れた「換算した inch」を外す — 2026-09-14

`scrapers/uniqlo_ut_sizepage.py` の初回走行 (2026-09-14 午後・途中で停止) は、
公式サイズページの cm に加えて **cm を換算した inch を `size_chart_inch` に入れていた**。
窓口の指示 (`requests/2026-09-13_ut_size_chart_for_gone_products_response.md`) は
「公式の cm をそのまま保存。inch に換算して保存しない」。出品くんは `size_chart_inch` を
そのまま写すので、換算値が出品に出てしまう。

対象: `size_chart_source` が `official_size_page` で始まる行 (= この走行で書いた行だけ)。
`size_chart_inch` と `size_chart_inch_note` を消し、cm (`size_chart`) は残す。

実行:
    python migrations/2026-09-14_uniqlo_ut_sizepage_drop_converted_inch.py            # dry-run
    python migrations/2026-09-14_uniqlo_ut_sizepage_drop_converted_inch.py --commit
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime

DB = "C:/dev/iMak_data/catalog/products.sqlite"
Q = ("SELECT id, specs FROM products WHERE category='uniqlo_ut' "
     "AND json_extract(specs,'$.size_chart_source') LIKE 'official_size_page%' "
     "AND json_extract(specs,'$.size_chart_inch') IS NOT NULL")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def main(commit: bool) -> None:
    db = sqlite3.connect(DB, timeout=120)
    rows = db.execute(Q).fetchall()
    now = datetime.now().isoformat(timespec="seconds")
    if commit:
        for rid, sp in rows:
            s = json.loads(sp)
            s.pop("size_chart_inch", None)
            s.pop("size_chart_inch_note", None)
            db.execute("UPDATE products SET specs=?, updated_at=? WHERE id=?",
                       (json.dumps(s, ensure_ascii=False), now, rid))
        db.commit()
    print(f"対象 {len(rows)}行 / 残り {len(db.execute(Q).fetchall())}行 / "
          f"{'commit' if commit else 'dry-run'}")


if __name__ == "__main__":
    main("--commit" in sys.argv)
