"""OPCG specs field 名重複の正規化 (= 大文字始 → 小文字 snake_case 統一).

依頼: OPCG 公式 import (= commit 2026-05-30) で
  Bandai 既存 (= Color/Card Type/Rarity 等 大文字始)
  + OPCG 公式 (= color/card_type/rarity 等 小文字)
  が併存し catalog field が重複している。

正規化 mapping:
  Color           → color
  Card Type       → card_type
  Attribute       → attribute
  Rarity          → rarity
  Power           → power
  Cost/Life       → cost (= leader Life ≈ cost 同等)
  Counter+        → counter
  Illust Type     → illustration_type
  Type            → card_characteristics  (= 別 field、 既存 card_type と衝突回避)

flow:
  - 1 entry の specs を read
  - 大文字 key の値を 小文字 key に migrate (= 既存値あれば上書きしない)
  - 大文字 key を delete

実行:
  python iMakCatalog/migrations/2026-05-30_opcg_field_normalize.py --probe
  python iMakCatalog/migrations/2026-05-30_opcg_field_normalize.py
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

DB_PATH = str(api._DB_PATH)
NOW = datetime.now().isoformat()

MAPPING = {
    "Color": "color",
    "Card Type": "card_type",
    "Attribute": "attribute",
    "Rarity": "rarity",
    "Power": "power",
    # ★2026-08-22 是正: Leader の "Cost/Life" は **ライフ** であってコストではない。
    #   公式 API (bandai-tcg-plus /api/user/card/66038 = OP06-022 Yamato) が
    #   Card Type=Leader / Cost/Life=4 を返す。この 4 はライフ。
    #   旧コメントは「leader Life ≈ cost 同等」と書いて cost に寄せていたが、
    #   出品に出すと **公式に無いコストを出す**ことになる (HQ 指摘 2026-08-22)。
    #   → Leader は life、それ以外は cost に入れる (_key_for_cost_life)。
    "Cost/Life": "__cost_or_life__",
    "Counter+": "counter",
    "Illust Type": "illustration_type",
    "Type": "card_characteristics",
}


def _key_for_cost_life(specs: dict) -> str:
    """Leader なら life、そうでなければ cost."""
    ct = str(specs.get("card_type") or specs.get("Card Type") or "").upper()
    return "life" if "LEADER" in ct else "cost"


def normalize_specs(specs: dict) -> tuple[dict, dict]:
    """正規化後の specs dict と 変更内訳 を返す."""
    out = dict(specs)
    changes = {"migrated": 0, "kept_existing": 0, "deleted": 0}
    for old_key, new_key in MAPPING.items():
        if old_key not in out:
            continue
        if new_key == "__cost_or_life__":
            new_key = _key_for_cost_life(out)
        old_val = out.pop(old_key)
        changes["deleted"] += 1
        # 既存 new_key に値があれば、 上書きしない (= 小文字 snake_case の方を信頼)
        if new_key in out and out[new_key] not in (None, "", []):
            changes["kept_existing"] += 1
            continue
        # new_key 未設定 or 空 → migrate
        if old_val not in (None, "", []):
            out[new_key] = old_val
            changes["migrated"] += 1
    return out, changes


def process(dry_run: bool):
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    rs = db.execute(
        "SELECT id, specs FROM products WHERE category='one_piece_tcg'"
    ).fetchall()
    total = len(rs)
    affected = 0
    migrated_total = 0
    kept_total = 0
    deleted_total = 0
    for r in rs:
        if not r["specs"]:
            continue
        try:
            specs = json.loads(r["specs"])
        except Exception:
            continue
        new_specs, ch = normalize_specs(specs)
        if ch["deleted"] == 0:
            continue
        affected += 1
        migrated_total += ch["migrated"]
        kept_total += ch["kept_existing"]
        deleted_total += ch["deleted"]
        if not dry_run:
            db.execute(
                "UPDATE products SET specs=?, updated_at=? WHERE id=?",
                (json.dumps(new_specs, ensure_ascii=False), NOW, r["id"]),
            )
    if not dry_run:
        db.commit()
    db.close()
    print(f"total OPCG entries: {total}")
    print(f"affected entries:   {affected}")
    print(f"  migrated values:  {migrated_total}")
    print(f"  kept existing:    {kept_total}")
    print(f"  total deleted:    {deleted_total}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--probe", action="store_true")
    args = p.parse_args()
    print(f"=== OPCG field normalize ({'DRY-RUN' if args.probe else 'APPLY'}) ===")
    process(dry_run=args.probe)


if __name__ == "__main__":
    main()
