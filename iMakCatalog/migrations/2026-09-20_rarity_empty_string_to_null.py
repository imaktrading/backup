# -*- coding: utf-8 -*-
"""空文字の rarity / rarity_ebay を None に揃える (2026-09-20).

判定 (1丁目1番地): **①カタログのデータ**。値の中身ではなく**空の形が2通りある**問題。

依頼 `catalog/requests/2026-09-18_pokemon_rarity_missing_6.md` 項2 で
「CLL-008 だけ None ではなく空文字。同じ経路の他件も同様では」と指摘された分。

出品側はどちらでも空欄になる (fail-closed) ので出品への実害は無いが、
**空の形が2通りあると数える側が食い違う** (`IS NULL` で数えると空文字が漏れる)。
値を足すのではなく、空の形を1つにする。

★rarity そのものは入れない。公式ページにレアリティ表示が無いカードが在るため
  (2026-08-22 確定「Rarity の空欄は公式に無い = 天井」)。第三者サイトから値は取らない。

実行:
  python migrations/2026-09-20_rarity_empty_string_to_null.py [--commit]
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import api  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

FIELDS = ("rarity", "rarity_ebay")


def find(db):
    out = []
    for rid, cat, src, specs in db.execute(
            # ★遊戯王は出品していないので触らない (ユーザー確定 2026-09-03)。117行 該当するが対象外
            "SELECT id, category, source, specs FROM products "
            "WHERE specs LIKE '%rarity%' AND category <> 'yugioh_tcg'"):
        s = json.loads(specs or "{}")
        if any(s.get(f) == "" for f in FIELDS):
            out.append((rid, cat, src, s))
    return out


def main(commit: bool) -> None:
    db = api._connect()
    rows = find(db)
    by = Counter((cat, src) for _, cat, src, _ in rows)
    for (cat, src), n in by.most_common():
        print(f"  {cat:15} {src[:60]:60} {n:5}行")
    print(f"  合計 {len(rows)}行")

    if not commit:
        print("dry-run (書いていない)")
        return

    now = datetime.now().isoformat(timespec="seconds")
    for rid, _, _, s in rows:
        for f in FIELDS:
            if s.get(f) == "":
                s[f] = None
        db.execute("UPDATE products SET specs=?, updated_at=? WHERE id=?",
                   (json.dumps(s, ensure_ascii=False), now, rid))
    db.commit()
    print(f"書いた {len(rows)}行 / 残り {len(find(db))}行")


if __name__ == "__main__":
    main("--commit" in sys.argv)
