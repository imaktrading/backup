"""その種別が持ち得ない項目を空にする (ワンピ Leader の cost 105行 / ポケモン化石の HP 43行).

## 1. ワンピの Leader に `cost` が入っている 105行

Leader はコストを持たず「ライフ」を持つ。2026-08-22 に base 503行を直したが、
**variant (`_p` / `_P` 等) が取りこぼされていた**。同じカードで値も一致する:

    OP13-001    cost=None  life='4'   (2026-08-22 修正済)
    OP13-001_p  cost='4'   life=None  ← これ

→ `cost` を `life` に移して `cost` を空にする。

## 2. ポケモンの Trainer-Item に `hp` が入っている 43行

「古びた〇〇の化石」= グッズ。効果テキストに「HP60のたねポケモンとして…」と書いてあり、
本文から `HP 60` を拾っていた。**カードの HP ではない**ので出さない。
Stage (08-23) / 種別 (08-25) と同じ形。

    M3-068 古びたアゴの化石  hp='60' hp_ebay='60'  -> 空

実行:
  python migrations/2026-08-25_type_impossible_fields.py           # dry-run
  python migrations/2026-08-25_type_impossible_fields.py --commit
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


def run(commit: bool) -> None:
    db = sqlite3.connect(Path(api._DB_PATH))
    db.row_factory = sqlite3.Row
    updates = []

    print("=== 1. ワンピ Leader の cost -> life (%s) ==="
          % ("APPLY" if commit else "DRY-RUN"))
    rows = db.execute(
        "SELECT id, product_id, specs FROM products WHERE category='one_piece_tcg' "
        "AND json_extract(specs,'$.card_type_ebay')='Leader' "
        "AND coalesce(json_extract(specs,'$.cost'),'')<>''").fetchall()
    for r in rows:
        s = json.loads(r["specs"])
        cost = s.pop("cost")
        if not (s.get("life") or ""):
            s["life"] = cost
        s["leader_cost_fix"] = "2026-08-25_life_not_cost_variants"
        updates.append((json.dumps(s, ensure_ascii=False), NOW, r["id"]))
    print(f"   {len(rows)} 行 (例: {[r['product_id'] for r in rows[:4]]})")

    print("\n=== 2. ポケモン Trainer / Energy の hp を空に ===")
    rows2 = db.execute(
        "SELECT id, product_id, specs FROM products WHERE category='pokemon_tcg' "
        "AND json_extract(specs,'$.card_type_ebay') NOT IN ('Pokémon','Pokémon Tool') "
        "AND (coalesce(json_extract(specs,'$.hp'),'')<>'' "
        "     OR coalesce(json_extract(specs,'$.hp_ebay'),'')<>'')").fetchall()
    for r in rows2:
        s = json.loads(r["specs"])
        s.pop("hp", None)
        s.pop("hp_ebay", None)
        s["hp_fix"] = "2026-08-25_trainer_has_no_hp"
        updates.append((json.dumps(s, ensure_ascii=False), NOW, r["id"]))
    print(f"   {len(rows2)} 行 (例: {[r['product_id'] for r in rows2[:4]]})")

    if commit:
        db.executemany("UPDATE products SET specs=?, updated_at=? WHERE id=?", updates)
        db.commit()
        print(f"\n[OK] 適用 {len(updates)} 行")
    else:
        print(f"\n対象 {len(updates)} 行 (dry-run — --commit で適用)")
    db.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--commit", action="store_true")
    run(p.parse_args().commit)
