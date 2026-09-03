"""1セットに2つの値が入っていた3セットを揃える (2026-09-04).

判定: **①カタログのデータが誤り** → catalog 側で直す。
2026-09-04 のポケモン取り込みで新しい行が入り、既存行と値が食い違った。
`tests/test_one_set_one_value_20260902.py` が検出。

    ハイクラスパック「THE BEST OF XY」
        'Evolutions' (4行) は **英語版の別セット名** → 'The Best of XY' に統一 (規約③)
    ポケモンカードゲームDPtギフトボックス（ピカチュウデッキ）
        'Platinum' (4行) は **英語版の拡張パック名**。eBay master に商品そのものの値
        'DPt Gift Box (Pikachu)' が在るので そちらに統一 (規約①)
    スターターセット テラスタル「ミュウツーex」「ラウドボーンex」
        'Mewtwo ex Starter Deck' (4行) はセット名の片方しか指していない。
        official が2商品の合成名なので、合成した値に統一する

実行:
  python migrations/2026-09-04_three_set_conflicts.py [--commit]
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
# (set_name_official, 直す値, 正しい値)
T = [
    ("ハイクラスパック「THE BEST OF XY」", "Evolutions", "The Best of XY"),
    ("ポケモンカードゲームDPtギフトボックス（ピカチュウデッキ）", "Platinum", "DPt Gift Box (Pikachu)"),
    ("スターターセット テラスタル「ミュウツーex」「ラウドボーンex」", "Mewtwo ex Starter Deck",
     "Sv: Mewtwo Ex & Skeledirge Ex Terastal Starter Sets"),
]


def run(commit: bool) -> None:
    db = sqlite3.connect(Path(api._DB_PATH))
    db.row_factory = sqlite3.Row
    print(f"=== 1セット1値に揃える ({'APPLY' if commit else 'DRY-RUN'}) ===")
    n = 0
    for so, wrong, right in T:
        rows = db.execute(
            "SELECT id, product_id, specs FROM products WHERE category='pokemon_tcg' "
            "AND set_name_official=? AND json_extract(specs,'$.set_name_ebay')=?",
            (so, wrong)).fetchall()
        print(f"  {so}\n    {wrong!r} -> {right!r} : {len(rows)}行")
        for r in rows:
            s = json.loads(r["specs"] or "{}")
            s["set_name_ebay"] = right
            s["set_name_ebay_source"] = "set_conflict_fix_20260904"
            if commit:
                db.execute("UPDATE products SET specs=?, updated_at=? WHERE id=?",
                           (json.dumps(s, ensure_ascii=False), NOW, r["id"]))
        n += len(rows)
    if commit:
        db.commit()
    db.close()
    print("")
    print(f"{'適用' if commit else '(dry-run — --commit で適用)'} {n} 行")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--commit", action="store_true")
    run(p.parse_args().commit)
