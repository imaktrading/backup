# -*- coding: utf-8 -*-
"""メガ○○ex の英語名を規則で入れる (2026-09-05).

判定 (1丁目1番地): **①カタログのデータが足りない**。英語名が無いと出品できない。

## なぜ規則で入れてよいか

`メガ<ポケモン名>ex` は **catalog に既に 37行**あり、全部 `M <English> ex` の形で入っている
(`メガゲッコウガex` -> `M Greninja-ex` 等)。ポケモン名の部分は **PokeAPI で日本語から
英語が引ける**ので、推測が入るのは「M … ex」の枠だけで、それは既存行の書き方に合わせる。

★`メガヤンマ` のように **メガで始まるが メガシンカではない**ポケモンが在るので、
  まず名前全体を PokeAPI で引き、引けた場合はそちらを優先する (規則を当てない)。

★引けないもの (トレーナーズ / スタジアム / エネルギー、および英語版が出ていないカード) は
  **空欄のまま**。英語名が存在しないものを作らない。

実行:
  python migrations/2026-09-05_pokemon_mega_ex_name_en.py [--commit]
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scrapers"))
import api  # noqa: E402
import pokemon_name_translation as T  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

NOW = datetime.now().isoformat(timespec="seconds")
SRC = "mega_ex_rule_20260905"


def english(name: str, d1: dict, d2: dict) -> str | None:
    """`メガ○○ex` -> `M <English> ex`。当たらなければ None."""
    g = T.resolve_name_en(name, d1, d2)          # メガヤンマ 等は先にこちらで当たる
    if (g[0] if isinstance(g, tuple) else g):
        return None                              # 規則を当てる相手ではない
    m = re.match(r"^メガ(.+?)(ex|EX)$", name)
    if not m:
        return None
    base = m.group(1)
    tail = ""
    if base.endswith(("X", "Y")):                # メガリザードンYex
        base, tail = base[:-1], " " + base[-1]
    g = T.resolve_name_en(base, d1, d2)
    got = g[0] if isinstance(g, tuple) else g
    return f"M {got}{tail} ex" if got else None


def run(commit: bool) -> None:
    d1, d2 = T.load_pokeapi_dict(), T.load_api_dict()
    db = sqlite3.connect(str(api._DB_PATH))
    db.row_factory = sqlite3.Row
    rows = db.execute("SELECT id, product_id, name FROM products WHERE category='pokemon_tcg' "
                      "AND IFNULL(name_en,'')='' AND name LIKE 'メガ%'").fetchall()
    fix = [(r["id"], r["product_id"], r["name"], english(r["name"], d1, d2)) for r in rows]
    ok = [x for x in fix if x[3]]
    print(f"=== メガ○○ex の英語名 ({'APPLY' if commit else 'DRY-RUN'}) — "
          f"対象 {len(rows)}行 / 入れられる {len(ok)}行 ===")
    seen = set()
    for _id, pid, jp, en in ok:
        if jp not in seen:
            print(f"    {jp:<18s} -> {en}")
            seen.add(jp)
    for _id, pid, jp, en in fix:
        if not en:
            print(f"    · {pid} {jp} は空欄のまま (規則の対象外)")
    if commit:
        for _id, _pid, _jp, en in ok:
            db.execute("UPDATE products SET name_en=?, name_en_source=?, updated_at=? "
                       "WHERE id=?", (en, SRC, NOW, _id))
        db.commit()
    db.close()
    print("")
    print(f"{'適用' if commit else '(dry-run — --commit で適用)'} {len(ok)} 行")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    run(ap.parse_args().commit)


if __name__ == "__main__":
    main()
