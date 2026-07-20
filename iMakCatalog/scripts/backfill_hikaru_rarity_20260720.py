"""ひかるポケモン (ic_hikaru) の rarity 欠落 backfill — 2026-07-20

真因: scrapers/pokemon_tcg.py の rarity 抽出が `rarity/ic_rare_*.gif` のみ match していたため、
公式が別命名で出す `ic_hikaru.gif` (ひかるポケモン) を取りこぼし rarity=NULL のまま登録していた。
→ C:Rarity 空 → 出品側で必須 Item Specific 欠落 (pdca 層A: m68129506725 Shining Celebi)。

裏取り:
  - 公式 pokemon-card.com card/34000 (ひかるセレビィ) / card/34053 (ひかるレックウザ)
    = rarity 画像 `assets/images/card/rarity/ic_hikaru.gif` (文字コード表記なし)
  - 小売表記 [H] (遊々亭 / カーナベル) / [☆] (駿河屋) = JP コードは 'H' を採用
  - eBay 公式 facet = 'Shiny Holo Rare' (ebay.com browse node
    "Pokemon TCG Shining Legends ... Shiny Holo Rare in Japanese" で実在確認)
        ※ 'Shining Holo Rare' ではない。facet 文字列そのままを rarity_ebay に入れる。

対象は「rarity が空 かつ rarity_ebay も空 かつ name が ひかる〜」に限定 (fail-closed: 推測で広げない)。
promo 版 (S8a-P-010 ひかるコイキング / SM-P-083 ひかるホウオウ) は既に rarity_ebay='Promo' が
入っており C:Rarity は埋まるので対象外 (= promo は 'Promo' 表記が正、pokemon_promo_rarity_promo_policy)。
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timezone

DB = "C:/dev/iMak_data/catalog/products.sqlite"
RARITY_JP = "H"
RARITY_EBAY = "Shiny Holo Rare"
SPEC_SOURCE = "pokemon_card_official_ic_hikaru_ebay_facet_confirmed_20260720"

SELECT = """
select id, product_id, name, specs
  from products
 where category = 'pokemon_tcg'
   and name like 'ひかる%'
   and (json_extract(specs, '$.rarity') is null or json_extract(specs, '$.rarity') = '')
   and (json_extract(specs, '$.rarity_ebay') is null or json_extract(specs, '$.rarity_ebay') = '')
 order by product_id
"""


def main(apply: bool) -> int:
    conn = sqlite3.connect(DB)
    rows = conn.execute(SELECT).fetchall()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    for rid, pid, name, specs_json in rows:
        specs = json.loads(specs_json)
        specs["rarity"] = RARITY_JP
        specs["rarity_ebay"] = RARITY_EBAY
        specs["spec_source"] = SPEC_SOURCE
        specs["note"] = (specs.get("note", "") + " " if specs.get("note") else "") + (
            "ひかるポケモン。公式はマーク画像(ic_hikaru)のみで文字コード無し→小売表記[H]を JP コードとして採用。"
        ).strip()
        print(f"{'APPLY' if apply else 'DRY '} {pid} {name} → rarity='{RARITY_JP}' / C:Rarity='{RARITY_EBAY}'")
        if apply:
            conn.execute(
                "update products set specs = ?, updated_at = ? where id = ?",
                (json.dumps(specs, ensure_ascii=False), now, rid),
            )
    if apply:
        conn.commit()
    print(f"--- {len(rows)} rows ({'applied' if apply else 'dry-run'})")
    return len(rows)


if __name__ == "__main__":
    main(apply="--apply" in sys.argv)
