"""card_size_ebay の空欄 2,859行を 'Standard' で埋める.

## なぜ埋めてよいか (推測ではない)

`card_size_ebay` に入っている値は **`Standard` の1種類だけ** (86,280行)。
category / 種別による違いは無く、空欄の行も種別はバラバラ (Battle / Pokémon / Unit …) で
「小さいカード」等の区別があるわけではない。= 単に埋め損ねている行。

`game_ebay` / `manufacturer_ebay` は同じ性質の定数で 100% 埋まっているので、
`card_size_ebay` だけ 96% なのは取りこぼし。

## やらないこと

**特大カード (ジャンボ等) の区別はしない。** 元データに大きさの項目が無く、
今の86,280行も promo を含めて全部 Standard。区別が要るようになったら、
その時に元データを取り直す。

実行:
  python migrations/2026-08-25_card_size_fill_constant.py           # dry-run
  python migrations/2026-08-25_card_size_fill_constant.py --commit
"""
from __future__ import annotations

import argparse
import json
import sqlite3
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

NOW = datetime.now().isoformat(timespec="seconds")
CATS = ("pokemon_tcg", "one_piece_tcg", "gundam_tcg", "dragonball_scg", "yugioh_tcg")


def run(commit: bool) -> None:
    db = sqlite3.connect(Path(api._DB_PATH))
    db.row_factory = sqlite3.Row
    # 念のため: Standard 以外の値が在るなら止める (前提が崩れている)
    other = {v for (v,) in db.execute(
        "SELECT DISTINCT json_extract(specs,'$.card_size_ebay') FROM products "
        "WHERE coalesce(json_extract(specs,'$.card_size_ebay'),'')<>''")}
    if other - {"Standard"}:
        print(f"✗ Standard 以外の値が在る {other} → 中止 (定数の前提が崩れている)")
        db.close()
        return

    per, updates = Counter(), []
    for r in db.execute(
            "SELECT id, category, specs FROM products WHERE category IN (%s)"
            % ",".join("?" * len(CATS)), CATS).fetchall():
        s = json.loads(r["specs"] or "{}")
        if (s.get("card_size_ebay") or ""):
            continue
        s["card_size_ebay"] = "Standard"
        s["card_size_source"] = "constant_fill_20260825"
        per[r["category"]] += 1
        updates.append((json.dumps(s, ensure_ascii=False), NOW, r["id"]))

    print("=== card_size_ebay の穴埋め (%s) ===" % ("APPLY" if commit else "DRY-RUN"))
    for k, v in per.most_common():
        print(f"   {k:16s} {v}")
    print(f"   合計 {len(updates)} 行")
    if commit:
        db.executemany("UPDATE products SET specs=?, updated_at=? WHERE id=?", updates)
        db.commit()
        print("[OK] 適用")
    else:
        print("(dry-run — --commit で適用)")
    db.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--commit", action="store_true")
    run(p.parse_args().commit)
