"""DBSCG 新セット未マージ base の rarity 欠落 backfill — 2026-07-21

真因 (dbfw_dual_source_duplication の新セット版):
  FB06/FB07/E/FP/SB01/FS08-10 等の新セットは、base 行が dbfw_official (rarity 空) のまま
  残り、rarity を持つ bandai 行が `{base}_dummy_s1` に取り残されて **base にマージされていない**。
  resolver は full-pid exact で base を返すため C:Rarity 空 → fail-closed skip (alt でない通常カードが
  出品できない)。旧セット(FB05等)は base = 'bandai_tcg_plus+dbfw_official' に merge 済で rarity 有り。

修正方針 (read-side/正規化と同じリスク階級。KEY/alias_of/dedup 非接触):
  base 行の rarity/rarity_ebay を、**同番・非PARA・非★ の bandai 兄弟**からコピーする。
  - **名前一致ガード必須**: name または name_en が base と一致する兄弟のみ採用。
    (同番でも dbfw と bandai が別カードを持つ番号分裂が実在: 例 FB07-025 base=Omega Shenron /
     _dummy_s1=Syn Shenron。ガードでこれを弾く = 誤 rarity 注入を構造的に防止。)
  - 兄弟の rarity が複数候補で不一致なら skip (曖昧 → fail-closed)。
  - ENERGY MARKER / DON / Resource / Token 系は rarity 非該当なので **対象外**
    (card_type in BATTLE/EXTRA/LEADER のみ)。
  - 兄弟が無い / base rarity を持つ兄弟が無い (_P/_RE のみ等) → 空のまま (fail-closed)。

適用は spec_source で来歴を残す。将来の正規 dual-source マージが来れば上書きされる。
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timezone

DB = "C:/dev/iMak_data/catalog/products.sqlite"
CAT = "dragonball_scg"
SPEC_SOURCE = "bandai_sibling_base_rarity_backfill_20260721"
TARGET_TYPES = ("BATTLE", "EXTRA", "LEADER")

BASE_NULL = """
select id, product_id, name, name_en, specs,
       json_extract(specs,'$.card_type') as ct
  from products
 where category = ?
   and product_id not like '%\\_%' escape '\\'
   and (json_extract(specs,'$.rarity') is null or json_extract(specs,'$.rarity') = '')
   and json_extract(specs,'$.card_type') in ('BATTLE','EXTRA','LEADER')
 order by product_id
"""

SIBS = """
select product_id, name, name_en,
       json_extract(specs,'$.rarity') as r,
       json_extract(specs,'$.rarity_ebay') as re
  from products
 where category = ?
   and product_id like ? escape '\\'
   and source like 'bandai%'
"""


def main(apply: bool) -> None:
    conn = sqlite3.connect(DB)
    rows = conn.execute(BASE_NULL, (CAT,)).fetchall()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    filled = skipped_nosib = skipped_mismatch = skipped_ambig = 0
    for rid, pid, name, name_en, specs_json, ct in rows:
        like = pid.replace("_", "\\_") + "\\_%"
        sibs = conn.execute(SIBS, (CAT, like)).fetchall()
        # 非PARA・非★・rarity 有り・名前一致
        cand = [
            s for s in sibs
            if "PARA" not in s[0]
            and s[3] and "★" not in s[3]
            and (s[1] == name or (name_en and s[2] == name_en))
        ]
        if not cand:
            # 名前一致しない rarity 兄弟が居るなら番号分裂の疑い
            any_rar = [s for s in sibs if "PARA" not in s[0] and s[3] and "★" not in s[3]]
            if any_rar:
                skipped_mismatch += 1
            else:
                skipped_nosib += 1
            continue
        rarities = {s[3] for s in cand}
        if len(rarities) > 1:
            skipped_ambig += 1
            print(f"  AMBIG {pid} {name}: {[(s[0], s[3]) for s in cand]}")
            continue
        src = cand[0]
        specs = json.loads(specs_json)
        specs["rarity"] = src[3]
        specs["rarity_ebay"] = src[4] or src[3]
        specs["spec_source"] = SPEC_SOURCE
        specs["note"] = ((specs.get("note", "") + " ") if specs.get("note") else "") + (
            f"rarity backfilled from bandai sibling {src[0]} (dual-source 未マージ base; "
            "name-guarded, KEY/alias 非接触)."
        )
        filled += 1
        if filled <= 20 or not apply:
            print(f"{'APPLY' if apply else 'DRY '} {pid} {name} ← {src[0]} rarity={src[3]} / ebay={src[4]}")
        if apply:
            conn.execute("update products set specs=?, updated_at=? where id=?",
                         (json.dumps(specs, ensure_ascii=False), now, rid))
    if apply:
        conn.commit()
    print(f"--- total {len(rows)} | filled {filled} | "
          f"skip: no-sib {skipped_nosib}, name-mismatch {skipped_mismatch}, ambiguous {skipped_ambig} "
          f"({'applied' if apply else 'dry-run'})")


if __name__ == "__main__":
    main(apply="--apply" in sys.argv)
