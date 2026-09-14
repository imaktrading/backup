"""UT の実寸表で「cm」と書いてあるのに中身が inch の行の単位を直す — 2026-09-14

実測 (2026-09-14): size_chart_unit='cm' の 1,609行のうち **1,521行は size_chart と
size_chart_inch が同じ** (= `25 1/4` のような inch の値)。

原因: `uniqlo_ut_sizechart.fetch_chart` が cm を押さずに読んでいた。公式は単位の選択を
覚えているので、同じブラウザの2件目以降は inch のまま開いていた (scraper は同日修正)。

出品くんが写すのは `size_chart_inch` なので **出品の値は正しい**。誤っているのは
`size_chart` に「cm」と書いた札だけ。本当の cm は取れていないので、札を inch に直す
(cm の値を作らない = 推測しない)。

実行:
    python migrations/2026-09-14_uniqlo_ut_size_chart_unit_inch_relabel.py            # dry-run
    python migrations/2026-09-14_uniqlo_ut_size_chart_unit_inch_relabel.py --commit
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime

DB = "C:/dev/iMak_data/catalog/products.sqlite"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def main(commit: bool) -> None:
    db = sqlite3.connect(DB, timeout=120)
    now = datetime.now().isoformat(timespec="seconds")
    n = 0
    for rid, sp in db.execute("SELECT id, specs FROM products WHERE category='uniqlo_ut' "
                              "AND json_extract(specs,'$.size_chart_unit')='cm'").fetchall():
        s = json.loads(sp)
        if not s.get("size_chart") or s.get("size_chart") != s.get("size_chart_inch"):
            continue
        n += 1
        if commit:
            s["size_chart_unit"] = "inch"
            s["size_chart_unit_fixed_at"] = now
            s["size_chart_unit_note"] = "cm を押さずに読んだため中身は inch だった。cm は未取得"
            db.execute("UPDATE products SET specs=?, updated_at=? WHERE id=?",
                       (json.dumps(s, ensure_ascii=False), now, rid))
    if commit:
        db.commit()
    left = sum(1 for (sp,) in db.execute(
        "SELECT specs FROM products WHERE category='uniqlo_ut' "
        "AND json_extract(specs,'$.size_chart_unit')='cm'")
        if json.loads(sp).get("size_chart") == json.loads(sp).get("size_chart_inch"))
    print(f"対象 {n}行 / 残り (cm なのに inch と同じ) {left}行 / {'commit' if commit else 'dry-run'}")


if __name__ == "__main__":
    main("--commit" in sys.argv)
