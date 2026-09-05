# -*- coding: utf-8 -*-
"""公式と食い違っていた最後の3行を直す (2026-09-05).

判定 (1丁目1番地): **①カタログのデータが誤り**。公式ページを取り直して1枚ずつ確認した。

    OP17-033     rarity 'TR' -> 'R'
        公式は同じ番号を2行で出す: 通常が `R`、`OP17-033_p1` が `TR` (トレジャーレア)。
        catalog は通常の行にも TR が入っていた = **別の刷りのレアリティ**。

    P-105_p2     rarity 'SP P' -> 'SPカード'
        公式の表記は `SPカード`。変換表に `SPカード -> Special` が在るので、
        eBay に出る値は `Promo` から `Special` に変わる (公式どおりになる)。

    OP13-001_p1  収録商品 `BOOSTER PACK -CARRYING ON HIS WILL-[OP-13]`
                        -> `一番くじ ONE PIECE CARD GAME 購入者特典`
        `_p1` は一番くじの配布分。ブースターの名前が入っていた。

実行:
  python migrations/2026-09-05_op_three_official_diffs.py [--commit]
"""
from __future__ import annotations

import argparse
import json
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
SRC = "official_diff_fix_20260905"
RARITY = [("OP17-033", "TR", "R"), ("P-105_p2", "SP P", "SPカード")]
SETNAME = [("OP13-001_p1", "一番くじ ONE PIECE CARD GAME 購入者特典")]


def run(commit: bool) -> None:
    db = sqlite3.connect(str(api._DB_PATH))
    db.row_factory = sqlite3.Row
    rmap = {r[0]: r[1] for r in db.execute(
        "SELECT source_value, ebay_value FROM ebay_filter_map "
        "WHERE category='one_piece_tcg' AND field='rarity'")}
    print(f"=== 公式との食い違い ({'APPLY' if commit else 'DRY-RUN'}) ===")
    for pid, was, want in RARITY:
        r = db.execute("SELECT id, specs FROM products WHERE category='one_piece_tcg' "
                       "AND product_id=?", (pid,)).fetchone()
        if not r:
            print(f"    ✗ {pid} が無い")
            continue
        s = json.loads(r["specs"] or "{}")
        if s.get("rarity") != was:
            print(f"    · {pid} は既に {s.get('rarity')!r}")
            continue
        s["rarity"] = want
        if want in rmap:
            s["rarity_ebay"] = rmap[want]
        print(f"    {pid:14s} rarity {was!r} -> {want!r} / eBay {s.get('rarity_ebay')!r}")
        if commit:
            db.execute("UPDATE products SET specs=?, updated_at=? WHERE id=?",
                       (json.dumps(s, ensure_ascii=False), NOW, r["id"]))
    for pid, want in SETNAME:
        r = db.execute("SELECT id, set_name_official FROM products "
                       "WHERE category='one_piece_tcg' AND product_id=?", (pid,)).fetchone()
        if not r:
            print(f"    ✗ {pid} が無い")
            continue
        print(f"    {pid:14s} 収録 {r['set_name_official']!r} -> {want!r}")
        if commit:
            db.execute("UPDATE products SET set_name=?, set_name_official=?, updated_at=? "
                       "WHERE id=?", (want, want, NOW, r["id"]))
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
