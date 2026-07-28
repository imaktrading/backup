"""Gundam の大文字 `Rarity` キー 318件を lowercase `rarity`/`rarity_ebay` に正規化 — 2026-07-28

依頼: requests/2026-07-28_priority_and_rarity_key_reconcile.md §3 (Advisor)。
gundam に `Rarity`(大文字R) が 318件 = 表記揺れ。集計者ごとに rarity 欠損数が食い違う原因。
主因は 2026-07-24 の新弾取込 (GD05 132 / EB01 105 / ST10 33) に gundam_field_normalize を
掛け忘れたこと (OP は opcg_field_normalize 済だった)。

方式: phase_b のハードコード辞書でなく、**既存 normalized gundam の実測 convention** で決定的に
変換 (rarity=Rarity値, rarity_ebay=CONV[値], 大文字 Rarity 削除)。未知値は fail-closed で触らない。
これにより新弾カードの C:Rarity が短縮 'LR' fallback → 正規 'Leader Rare' に改善 (既存規約一致)。

冪等 (再実行で capital-only が無ければ no-op)。
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timezone

DB = "C:/dev/iMak_data/catalog/products.sqlite"
CAT = "gundam_tcg"

# 既存 normalized gundam から実測した rarity -> rarity_ebay 規約
CONV = {
    "C": "Common", "R": "Rare", "U": "U", "LR": "Leader Rare", "SR": "Super Rare",
    "C+": "C+", "R+": "R+", "U+": "U+", "LR+": "LR+", "LR++": "LR++",
    "SPLR+": "SPLR+", "SPU+": "SPU+", "SPR+": "SPR+",
}


def run(apply: bool) -> None:
    conn = sqlite3.connect(DB)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    n = 0
    unmapped = set()
    for rid, sp in conn.execute(
        "select id, specs from products where category=?", (CAT,)
    ).fetchall():
        d = json.loads(sp)
        if "Rarity" in d and "rarity" not in d:
            val = d["Rarity"]
            if val not in CONV:
                unmapped.add(val)
                continue  # fail-closed: 未知は触らない
            d["rarity"] = val
            d["rarity_ebay"] = CONV[val]
            del d["Rarity"]
            d["spec_source"] = (d.get("spec_source", "") or "") + "|Rarity_key_normalized_20260728"
            n += 1
            if apply:
                conn.execute("update products set specs=?, updated_at=? where id=?",
                             (json.dumps(d, ensure_ascii=False), now, rid))
    if apply:
        conn.commit()
    print(f"normalized capital Rarity → rarity/rarity_ebay: {n} ({'applied' if apply else 'dry-run'})")
    if unmapped:
        print(f"unmapped (skipped, fail-closed): {unmapped}")


if __name__ == "__main__":
    run(apply="--apply" in sys.argv)
