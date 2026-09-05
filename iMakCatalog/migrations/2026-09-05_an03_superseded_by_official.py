# -*- coding: utf-8 -*-
"""3rd ANNIVERSARY の手作り行を、公式が載せた行に一本化する (2026-09-05).

## 経緯

3rd ANNIVERSARY SET は **公式が収録一覧を出していなかった**ので、PSA の現物から
1枚ずつ `_AN03` という内部キーで足していた (2026-08-26 / 08-29)。
CLAUDE.md「公式カードリストに無いカードを登録してよいか」の但し書きどおり、
**公式が載せたら公式値で上書きする**約束だった。

2026-09-05 に公式のプロモ一覧を取り直したところ、3枚とも公式に在った:

    OP12-079_AN03  ->  OP12-079_p1
    OP07-118_AN03  ->  OP07-118_p3
    ST15-005_AN03  ->  ST15-005_p2

同じカードの行が2つある状態は、出品くんの引き当てが揺れる (実際に
`ONE PIECE JAPANESE 3RD ANNIVERSARY SET #005` が どちらに当たるか不定になった)。

## やること

1. 手作り行が持っていた **英語名**を公式行に移す (公式ページは日本語しか出さない)。
2. 手作り行を消す。絵も公式のものに替わる (PSA のスラブ写真は仮置きだった)。

★HQ へ: `*_AN03` を鍵に使った出品が在れば、公式の `_pN` に読み替えが要る。
  この3枚は目視の候補に出た段階で、出品済みの想定はしていない。

実行:
  python migrations/2026-09-05_an03_superseded_by_official.py [--commit]
"""
from __future__ import annotations

import argparse
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

NOW = datetime.now().isoformat(timespec="seconds")
PAIRS = [("OP12-079_AN03", "OP12-079_p1"),
         ("OP07-118_AN03", "OP07-118_p3"),
         ("ST15-005_AN03", "ST15-005_p2")]


def run(commit: bool) -> None:
    db = sqlite3.connect(str(api._DB_PATH))
    db.row_factory = sqlite3.Row
    print(f"=== 手作り行を公式行に一本化 ({'APPLY' if commit else 'DRY-RUN'}) ===")
    for old, new in PAIRS:
        o = db.execute("SELECT id, name_en FROM products WHERE category='one_piece_tcg' "
                       "AND product_id=?", (old,)).fetchone()
        n = db.execute("SELECT id, name_en FROM products WHERE category='one_piece_tcg' "
                       "AND product_id=?", (new,)).fetchone()
        if not o:
            print(f"    · {old} は既に無い")
            continue
        if not n:
            print(f"    ✗ {new} が無い → {old} は残す (fail-closed)")
            continue
        print(f"    {old} -> {new}  英語名 {o['name_en']!r}")
        if commit:
            if o["name_en"] and not n["name_en"]:
                db.execute("UPDATE products SET name_en=?, name_en_source=?, updated_at=? "
                           "WHERE id=?", (o["name_en"], "an03_merge_20260905", NOW, n["id"]))
            db.execute("DELETE FROM products WHERE id=?", (o["id"],))
    if commit:
        db.commit()
    db.close()
    print("")
    print(f"{'適用' if commit else '(dry-run — --commit で適用)'}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    run(ap.parse_args().commit)


if __name__ == "__main__":
    main()
