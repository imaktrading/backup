# -*- coding: utf-8 -*-
"""ワンピの英語名の空欄を埋める (2026-09-05).

判定 (1丁目1番地): **①カタログのデータが足りない**。出品くんは英語名を出せないので
その行は出せない。埋める順は「確かなもの順」で、確証が無ければ空欄のまま (fail-closed)。

## 埋める順

1. **`name` 列に既に英語が入っている行** (258行)
   bandai の EN API から来た行は `name`=英語 / `name_jp`=日本語 で、`name_en` だけ空だった。
   移すだけ。新しい値は作らない。
2. **公式の英語版カードリスト** (bandai-tcg-plus `game_title_id=4`) から券面番号で引く
   同じ番号の英語版カード名。**公式値**なので推測ではない。
3. **catalog の同じ日本語名の行**が使っている英語名 (割れていないものだけ)

★どれにも当たらない行は空欄のまま。英語版が出ていないカードは英語名が存在しない。

実行:
  python migrations/2026-09-05_op_name_en_backfill.py [--commit]
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scrapers"))
import api  # noqa: E402
import one_piece_tcg as OP  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

NOW = datetime.now().isoformat(timespec="seconds")
CAT = "one_piece_tcg"
_LATIN = re.compile(r"^[\x20-\x7E’“”\-–—]+$")


def run(commit: bool) -> None:
    db = sqlite3.connect(str(api._DB_PATH))
    db.row_factory = sqlite3.Row

    # 3) 同じ日本語名 → 英語名 (割れていないものだけ)
    same: dict[str, set] = defaultdict(set)
    for jp, en in db.execute(
            f"SELECT name_jp, name_en FROM products WHERE category='{CAT}' "
            "AND IFNULL(name_jp,'')<>'' AND IFNULL(name_en,'')<>''"):
        same[jp].add(en)
    same = {k: next(iter(v)) for k, v in same.items() if len(v) == 1}

    rows = db.execute(
        f"SELECT id, product_id, name, name_jp, name_en FROM products "
        f"WHERE category='{CAT}' AND IFNULL(name_en,'')=''").fetchall()
    print(f"=== ワンピの英語名 ({'APPLY' if commit else 'DRY-RUN'}) — 空欄 {len(rows)}行 ===")

    # 2) 公式 EN カードリスト
    en_by_no: dict[str, set] = defaultdict(set)
    for c in OP.list_all_cards(4):
        no = (c.get("card_number") or "").strip()
        nm = (c.get("card_name") or "").strip()
        if no and nm:
            en_by_no[no].add(nm)
    en_by_no = {k: next(iter(v)) for k, v in en_by_no.items() if len(v) == 1}
    print(f"  公式 英語版カードリスト: {len(en_by_no)} 番号")

    how, done = Counter(), 0
    for r in rows:
        v = src = None
        if r["name"] and _LATIN.match(r["name"]) and (r["name_jp"] or "") != r["name"]:
            v, src = r["name"], "name_column_20260905"
        elif r["product_id"].split("_")[0] in en_by_no:
            v, src = en_by_no[r["product_id"].split("_")[0]], "official_en_list_20260905"
        elif (r["name_jp"] or "") in same:
            v, src = same[r["name_jp"]], "same_name_jp_20260905"
        if not v:
            how["空欄のまま (英語版が無い)"] += 1
            continue
        how[src] += 1
        if commit:
            db.execute("UPDATE products SET name_en=?, name_en_source=?, updated_at=? "
                       "WHERE id=?", (v, src, NOW, r["id"]))
            done += 1
            if done % 50 == 0:                     # 途中保存
                db.commit()
    if commit:
        db.commit()
    db.close()
    for k, v in how.most_common():
        print(f"    {v:5d}行  {k}")
    print("")
    print(f"{'適用' if commit else '(dry-run — --commit で適用)'}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    run(ap.parse_args().commit)


if __name__ == "__main__":
    main()
