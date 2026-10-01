# -*- coding: utf-8 -*-
"""Features の `Alt Art` を eBay の値 `Alternative Art` に揃える (2026-10-01).

## 判定: ① カタログのデータが誤り

同じ「別絵柄」を 2つの綴りで持っていた (2026-10-01 実測):

    Alt Art          3,005行   one_piece 1,416 / gundam 650 / dragonball 939
    Alternative Art  1,371行   gundam 449 / dragonball 921 / one_piece 1

eBay の値の一覧 (`_input/ebay_aspects_183454_latest.json` の `aspects.Features.all`) に
**`Alternative Art` は在り、`Alt Art` は無い**。Features は FREE_TEXT なので弾かれはしないが、
一覧に在る値が在るのに別の綴りを使うのは誤り (Set の §0c と同じ形)。
両方が入っている行は 0件なので、置き換えても重複しない。

見つかった経緯: PB01 の直し (`2026-10-01_gundam_pb01_official_setname.py`) で公式の行に
移したら、回帰テストが `Alternative Art` を期待して赤になった。消した複製行だけが
一覧どおりの綴りを持っていた。

実行: python migrations/2026-10-01_features_alt_art_to_ebay_value.py [--commit]
"""
from __future__ import annotations

import json
import sqlite3
import sys

DB = "C:/dev/iMak_data/catalog/products.sqlite"
OLD, NEW = "Alt Art", "Alternative Art"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def main() -> None:
    commit = "--commit" in sys.argv
    c = sqlite3.connect(DB, timeout=120)
    hits, by_cat = [], {}
    for rid, cat, pid, sp in c.execute("SELECT id, category, product_id, specs FROM products"):
        try:
            d = json.loads(sp or "{}")
        except ValueError:
            continue
        f = d.get("features")
        if not isinstance(f, list) or OLD not in f:
            continue
        if NEW in f:                      # 両方在る行は触らない (0件のはず)
            continue
        d["features"] = [NEW if x == OLD else x for x in f]
        hits.append((rid, json.dumps(d, ensure_ascii=False)))
        by_cat[cat] = by_cat.get(cat, 0) + 1
    print(f"=== Features {OLD!r} → {NEW!r} ({'APPLY' if commit else 'DRY-RUN'}) ===")
    for k, v in sorted(by_cat.items()):
        print(f"  {k:16} {v}行")
    print(f"  合計 {len(hits)}行")
    if not commit:
        print("(dry-run — --commit で適用)")
        return
    c.executemany("UPDATE products SET specs=? WHERE id=?", [(s, i) for i, s in hits])
    c.commit()
    left = 0
    for (sp,) in c.execute("SELECT specs FROM products WHERE specs LIKE '%Alt Art%'"):
        try:
            if OLD in (json.loads(sp or "{}").get("features") or []):
                left += 1
        except ValueError:
            pass
    print(f"適用した。残り {left}行")
    c.close()


if __name__ == "__main__":
    main()
