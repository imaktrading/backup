r"""name_en 空レコードを公式英名で補完 (Item Specifics 日本語漏れの根治).

背景: name_en が空だと listing が name_jp(日本語) に fallback し、eBay の
Item Specifics (Card Name / Character) に日本語が漏れる (RP-009 'リソース' 事件)。

★ 出品の正確性原則 / id_strict_with_explicit_rescue 厳守 = 推測翻訳しない。
   公式由来の英名が ID/名前で確定するものだけ補完。確証なければ空のまま。

補完ルール (= 推測ではなく公式由来):
  A) name_jp 一致伝播: 同一 name_jp を持つ「権威ある source」の filled レコードが
     一意な name_en を持つ場合、その公式英名を採用。
       - gundam/one_piece/dragonball: 原スクレイプ (name_en_source IS NULL) のみ採用
         (= character_name_sync や claude 翻訳は除外)
       - pokemon: pokeapi_official* / rule_trainer* のみ採用 (claude_api 汚染を除外)
     name_jp に対し複数 EN が並ぶ(曖昧/データ破損)場合は skip。
  B) gundam ユーティリティカード: name=type のカード (リソース/EXベース/EXリソース) は
     公式英名 = card_type 英名で確定 → 明示マッピングで補完。

対象外 (本 migration では触らない):
  - uniqlo_ut (商品名の性質が違う → 別途方針)
  - 上記で確定しないもの (ファトゥム-00 等のトークン名、no-match) → 空のまま

使い方:
  python migrations/2026-06-03_name_en_backfill.py            # dry-run
  python migrations/2026-06-03_name_en_backfill.py --commit   # backup + 実投入
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

DB = Path("C:/dev/iMak_data/catalog/products.sqlite")

# 伝播元として信頼する name_en_source (category 別)
AUTH_SOURCE = {
    "gundam_tcg":     lambda s: s is None,
    "one_piece_tcg":  lambda s: s is None,
    "dragonball_scg": lambda s: s is None,
    "pokemon_tcg":    lambda s: s in (
        "pokeapi_official", "pokeapi_official_suffix", "pokeapi_official_form",
        "rule_trainer_dict", "rule_trainer_owned"),
}

# gundam ユーティリティ (name=type) の公式英名 (card_type_ebay で実値確認済)
GUNDAM_UTILITY = {
    "リソース":   "Resource",
    "EXベース":   "EX Base",
    "EXリソース": "EX Resource",
}

PROP_SRC = "name_en_jp_propagate_20260603"
UTIL_SRC = "name_en_utility_20260603"


def run(commit: bool):
    print(f"=== name_en backfill {'(COMMIT)' if commit else '(DRY-RUN)'} ===")
    if commit:
        bak = DB.with_name(DB.name + ".pre_name_en_backfill_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
        shutil.copy2(DB, bak)
        print(f"✅ backup: {bak}\n")

    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    total_fill = 0

    for cat, authf in AUTH_SOURCE.items():
        rows = conn.execute(
            "select id, product_id, name_jp, name_en, name_en_source, "
            "json_extract(specs,'$.card_type') ct from products where category=?",
            (cat,)).fetchall()
        # 権威 source の name_jp -> {name_en}
        amap: dict[str, set] = {}
        for r in rows:
            ne = (r["name_en"] or "").strip()
            if ne and r["name_jp"] and authf(r["name_en_source"]):
                amap.setdefault(r["name_jp"], set()).add(ne)

        fills = []   # (id, name_en, src)
        amb = nomatch = 0
        for r in rows:
            if (r["name_en"] or "").strip():
                continue
            jp = r["name_jp"]
            # rule B: gundam utility (propagation より優先で確定)
            if cat == "gundam_tcg" and jp in GUNDAM_UTILITY:
                fills.append((r["id"], GUNDAM_UTILITY[jp], UTIL_SRC))
                continue
            # rule A: propagation
            if jp in amap and len(amap[jp]) == 1:
                fills.append((r["id"], next(iter(amap[jp])), PROP_SRC))
            elif jp in amap:
                amb += 1
            else:
                nomatch += 1

        print(f"--- {cat}: 補完 {len(fills)} (曖昧skip={amb} no-match={nomatch})")
        # sample 5
        for fid, en, src in fills[:5]:
            r = next(x for x in rows if x["id"] == fid)
            print(f"    {r['product_id']}: {r['name_jp']!r} -> {en!r}  [{src.split('_')[-1] if False else src}]")
        if commit:
            conn.executemany("update products set name_en=?, name_en_source=? where id=?",
                             [(en, src, fid) for fid, en, src in fills])
        total_fill += len(fills)

    if commit:
        conn.commit()
    conn.close()
    print(f"\n{'投入' if commit else '投入予定'} 合計: {total_fill} 件")
    if not commit:
        print("(DRY-RUN: DB 変更なし。 確認後 --commit)")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    run(ap.parse_args().commit)
