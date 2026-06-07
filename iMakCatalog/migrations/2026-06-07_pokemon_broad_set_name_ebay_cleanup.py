"""Pokemon set_name_ebay 広域 cleanup (HQ確定値 2026-06-07).

依頼: requests/2026-06-07_pokemon_set_name_ebay_broad_cleanup.md
正値: requests/2026-06-07_pokemon_broad_cleanup_value_confirm_hq_values.md (HQ ネット確定)

Mega系(M2/M2a/M3/M4=603件)に続く同根(5/30 migration 手動 JP_TO_EN)の誤マップ修正。
HQ 監査ツール catalog_set_audit.py の [1]クロス世代1058/[3]サブセット取違46組 が対象。
32 set_code を HQ ネット確定値で upsert + DPs は空欄化(旧世代名 Vivid Voltage 除去)。

正値原則: 日本語カード = JP セットの英語名(英語版合本名は使わない)。確定値なし=空欄(fail-closed)。
yaml汚染も検出(S7R=Skyscraping Perfect は別セットS7D摩天の名 → 正 Blue Sky Stream)。

実行:
  python iMakCatalog/migrations/2026-06-07_pokemon_broad_set_name_ebay_cleanup.py          # dry-run
  python iMakCatalog/migrations/2026-06-07_pokemon_broad_set_name_ebay_cleanup.py --commit
"""
from __future__ import annotations

import argparse
import json
import shutil
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

DB_PATH = Path(api._DB_PATH)
CATEGORY = "pokemon_tcg"
NOW = datetime.now().isoformat()

# product_id prefix -> 確定 eBay Set 値 (HQ ネット確定 2026-06-07)
CONFIRMED = {
    # --- group1 (yaml候補を HQ検証。微修正/汚染修正含む) ---
    "DPt2": "Bonds to the End of Time",   # yaml誤 "Bond at the End of Time"
    "DPt3": "Beat of the Frontier",       # yaml誤 "Frontier's Pulse"
    "DPt4": "Advent of Arceus",           # yaml誤 "Arceus Advent"
    "S6a": "Eevee Heroes",
    "S7R": "Blue Sky Stream",             # yaml汚染 "Skyscraping Perfect"(=S7D) 除去
    "S9": "Star Birth",
    "S10a": "Dark Phantasma",
    "S11a": "Incandescent Arcana",
    "SV2D": "Clay Burst",
    "SV2P": "Snow Hazard",
    "SV3a": "Raging Surf",
    "SV5K": "Wild Force",
    "SV5M": "Cyber Judge",
    "SV5a": "Crimson Haze",
    "SV7a": "Paradise Dragona",
    "SV8": "Super Electric Breaker",
    "SV9a": "Heat Wave Arena",
    # --- group2 (yaml無し、HQ ネット確定) ---
    "DPt1": "Galactic's Conquest",
    "DPtP": "Galactic's Conquest",
    "BW9": "Megalo Cannon",
    "L2": "Reviving Legends",
    "XY2": "Wild Blaze",
    "XY9": "Rage of the Broken Heavens",
    "S2a": "Explosive Walker",
    "S3a": "Legendary Heartbeat",
    "SM3H": "To Have Seen the Battle Rainbow",
    "SM4A": "Ultradimensional Beasts",
    "SM6b": "Champion Road",
    "SM8": "Super-Burst Impact",
    "SM10a": "GG End",
    "SM10b": "Sky Legend",
    "SM12": "Alter Genesis",
}
# 確定値なし → 空欄化 (旧別世代名を除去。fail-closed)
# DPP: HQ は「全件空」と想定だが監査で 1 件に旧 S&S 値が残存 → HQ意図(空欄)どおり除去
BLANK = {"DPs", "DPP"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()
    print(f"=== Pokemon broad set_name_ebay cleanup {'(COMMIT)' if args.commit else '(DRY-RUN)'} ===")

    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    rows = cur.execute("SELECT id, product_id, specs FROM products WHERE category=?",
                       (CATEGORY,)).fetchall()

    upd = []  # (id, pid, before, after)
    for r in rows:
        pre = (r["product_id"] or "").split("-")[0]
        try:
            d = json.loads(r["specs"]) if r["specs"] else {}
        except Exception:
            d = {}
        before = d.get("set_name_ebay")
        if pre in CONFIRMED:
            after = CONFIRMED[pre]
        elif pre in BLANK:
            after = ""
        else:
            continue
        if (before or "") != (after or ""):
            upd.append((r["id"], r["product_id"], pre, before, after, d))

    bypre = Counter(u[2] for u in upd)
    print(f"  変更要: {len(upd)} 件 / {len(bypre)} code")
    for pre in sorted(bypre):
        ex = next(u for u in upd if u[2] == pre)
        print(f"    {pre:6} {bypre[pre]:4}  {ex[3]!r} -> {ex[4]!r}")

    if not args.commit:
        print("\n  (DRY-RUN: DB 無変更)")
        con.close()
        return

    bak = DB_PATH.with_name(DB_PATH.name + ".pre_pokemon_broad_set_ebay_"
                            + datetime.now().strftime("%Y%m%d_%H%M%S"))
    shutil.copy2(DB_PATH, bak)
    print(f"  ✅ backup: {bak}")

    n = 0
    for _id, pid, pre, before, after, d in upd:
        if after == "":
            d.pop("set_name_ebay", None)
            d["set_name_ebay_source"] = "hq_blank_20260607"
        else:
            d["set_name_ebay"] = after
            d["set_name_ebay_source"] = "hq_confirmed_broad_20260607"
        cur.execute("UPDATE products SET specs=?, updated_at=? WHERE id=?",
                    (json.dumps(d, ensure_ascii=False), NOW, _id))
        n += 1
    con.commit()
    print(f"  ✅ 投入: {n} 件")
    con.close()


if __name__ == "__main__":
    main()
