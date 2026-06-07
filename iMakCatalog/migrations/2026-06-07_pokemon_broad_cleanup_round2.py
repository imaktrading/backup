"""Pokemon set_name_ebay 広域cleanup round-2 (HQ確定値 2026-06-07).

元: requests/2026-06-07_pokemon_broad_cleanup_round2_value_confirm_hq_values.md
round-1(33code/3056件)後の監査 [3] 残27組を解消。

HQ確定方針: 日本語カード=JPセット英語名(英語版合本名は不使用)。
キーは set_code でなく **set_name(JP)**(BW3/BW8/XY11 は1prefixに2デッキ混在のため)。
本migration は (prefix, set_name) 複合キーで精密適用(コード間衝突回避)。

Kind A(L2/019・DPt2/018・DPt4/017)= set_name(JP)空のサブ製品 → 空欄(fail-closed)。
本体(set_name有)は round-1 値のまま。

実行:
  python iMakCatalog/migrations/2026-06-07_pokemon_broad_cleanup_round2.py          # dry-run
  python iMakCatalog/migrations/2026-06-07_pokemon_broad_cleanup_round2.py --commit
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

# (product_id prefix, set_name(JP)) -> 確定 eBay Set 値 (HQ web確定 2026-06-07)
KINDB = {
    ("BW3", "拡張パック「サイコドライブ」"): "Psycho Drive",
    ("BW3", "拡張パック「ヘイルブリザード」"): "Hail Blizzard",
    ("BW8", "拡張パック「ラセンフォース」"): "Spiral Force",
    ("BW8", "拡張パック「ライデンナックル」"): "Thunder Knuckle",
    ("S1a", "拡張パック「VMAXライジング」"): "VMAX Rising",
    ("SM11a", "拡張パック「リミックスバウト」"): "Remix Bout",
    ("SM11b", "拡張パック「ドリームリーグ」"): "Dream League",
    ("SM1p", "拡張パック「サン＆ムーン」"): "Sun & Moon",
    ("SM2p", "拡張パック「新たなる試練の向こう」"): "Facing a New Trial",
    ("SM3N", "拡張パック「光を喰らう闇」"): "Darkness that Consumes Light",
    ("SM4S", "拡張パック「覚醒の勇者」"): "Awakened Heroes",
    ("SM6a", "拡張パック「ドラゴンストーム」"): "Dragon Storm",
    ("SM7a", "拡張パック「迅雷スパーク」"): "Thunderclap Spark",
    ("SM7b", "拡張パック「フェアリーライズ」"): "Fairy Rise",
    ("SM8a", "拡張パック「ダークオーダー」"): "Dark Order",
    ("SM9a", "拡張パック「ナイトユニゾン」"): "Night Unison",
    ("SM9b", "拡張パック「フルメタルウォール」"): "Full Metal Wall",
    ("XY11", "拡張パック「爆熱の闘士」"): "Fever-Burst Fighter",
    ("XY11", "拡張パック「冷酷の反逆者」"): "Cruel Traitor",
}
# Kind A: set_name(JP)空のサブ製品 → 空欄 (本体は round-1 値維持)
KINDA_BLANK_PREFIX = {"L2", "DPt2", "DPt4"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()
    print(f"=== round-2 cleanup {'(COMMIT)' if args.commit else '(DRY-RUN)'} ===")

    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    rows = cur.execute("SELECT id, product_id, set_name, specs FROM products WHERE category=?",
                       (CATEGORY,)).fetchall()

    upd = []
    for r in rows:
        pre = (r["product_id"] or "").split("-")[0]
        setn = r["set_name"]
        key = (pre, setn)
        if key in KINDB:
            after = KINDB[key]
            kind = "B"
        elif pre in KINDA_BLANK_PREFIX and not setn:
            after = ""
            kind = "A-blank"
        else:
            continue
        try:
            d = json.loads(r["specs"]) if r["specs"] else {}
        except Exception:
            d = {}
        before = d.get("set_name_ebay")
        if (before or "") != (after or ""):
            upd.append((r["id"], pre, setn, before, after, kind, d))

    bykey = Counter((u[1], u[2], u[4]) for u in upd)
    print(f"  変更要: {len(upd)} 件")
    for (pre, setn, after), n in sorted(bykey.items()):
        print(f"    {pre:6} {n:4}  set_name={setn!r:34} -> {after!r}")

    if not args.commit:
        print("\n  (DRY-RUN: DB 無変更)")
        con.close()
        return

    bak = DB_PATH.with_name(DB_PATH.name + ".pre_round2_"
                            + datetime.now().strftime("%Y%m%d_%H%M%S"))
    shutil.copy2(DB_PATH, bak)
    print(f"  ✅ backup: {bak}")
    n = 0
    for _id, pre, setn, before, after, kind, d in upd:
        if after == "":
            d.pop("set_name_ebay", None)
            d["set_name_ebay_source"] = "hq_blank_round2_20260607"
        else:
            d["set_name_ebay"] = after
            d["set_name_ebay_source"] = "hq_confirmed_round2_20260607"
        cur.execute("UPDATE products SET specs=?, updated_at=? WHERE id=?",
                    (json.dumps(d, ensure_ascii=False), NOW, _id))
        n += 1
    con.commit()
    print(f"  ✅ 投入: {n} 件")
    con.close()


if __name__ == "__main__":
    main()
