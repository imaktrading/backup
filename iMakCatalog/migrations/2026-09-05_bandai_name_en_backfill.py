# -*- coding: utf-8 -*-
"""ドラゴンボール / ガンダム の英語名の空欄を埋める (2026-09-05).

判定 (1丁目1番地): **①カタログのデータが足りない**。英語名が無い行は出品できない。

ワンピと同じ手順。**公式の英語版カードリスト** (bandai-tcg-plus) から券面番号で引く。
推測はしない。英語版が出ていないカードは空欄のまま (fail-closed)。

    dragonball_scg   game_title_id=10 (EN)
    gundam_tcg       game_title_id=16 (EN)

順番:
  1. `name` 列に既に英語が入っている行 → 移すだけ
  2. 公式の英語版カードリストの同じ券面番号
  3. catalog の同じ日本語名の行が使っている英語名 (割れていないものだけ)

実行:
  python migrations/2026-09-05_bandai_name_en_backfill.py [--commit]
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

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

NOW = datetime.now().isoformat(timespec="seconds")
GAMES = {"dragonball_scg": ("dragonball_scg", 10), "gundam_tcg": ("gundam_tcg", 16)}
_LATIN = re.compile(r"^[\x20-\x7E’“”\-–—]+$")


def run(cat: str, commit: bool) -> None:
    mod_name, game_id = GAMES[cat]
    mod = __import__(mod_name)
    db = sqlite3.connect(str(api._DB_PATH))
    db.row_factory = sqlite3.Row

    same: dict[str, set] = defaultdict(set)
    for jp, en in db.execute(
            "SELECT name_jp, name_en FROM products WHERE category=? "
            "AND IFNULL(name_jp,'')<>'' AND IFNULL(name_en,'')<>''", (cat,)):
        same[jp].add(en)
    same = {k: next(iter(v)) for k, v in same.items() if len(v) == 1}

    rows = db.execute("SELECT id, product_id, name, name_jp FROM products "
                      "WHERE category=? AND IFNULL(name_en,'')=''", (cat,)).fetchall()
    print(f"=== {cat} の英語名 ({'APPLY' if commit else 'DRY-RUN'}) — 空欄 {len(rows)}行 ===")

    en_by_no: dict[str, set] = defaultdict(set)
    for c in mod.list_all_cards(game_id):
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
            if done % 50 == 0:
                db.commit()
    if commit:
        db.commit()
    db.close()
    for k, v in how.most_common():
        print(f"    {v:5d}行  {k}")
    print("")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cat", choices=sorted(GAMES))
    ap.add_argument("--commit", action="store_true")
    a = ap.parse_args()
    for cat in ([a.cat] if a.cat else sorted(GAMES)):
        run(cat, a.commit)


if __name__ == "__main__":
    main()
