"""DBSCG BATTLE/EXTRA/LEADER の rarity 欠損 (925件) を name-guard backfill — 2026-07-28

依頼: requests/2026-07-28_go_si419_setbackfill_and_dbs925_rarity.md (Advisor 本実装 GO)。
分類 (2026-07-27_pokemon_MC742..._response §3): ENERGY MARKER 257 = (a) 空欄が正(除外)、
BATTLE 727 + EXTRA 114 + LEADER 84 = 925 = (b) 同base に rarity 持ち兄弟あり = recoverable。

方式 (2026-07-21 base backfill と同じ name-guard。[[dbscg_newset_unmerged_base_rarity]]):
  rarity 欠損の各カードに対し、**同 base・名前一致(name or name_en)・非★** の rarity 持ち兄弟から
  rarity + rarity_ebay を**両方コピー**する。
  - **番号分裂の罠を回避**: name 不一致の兄弟からはコピーしない (例 FB07-025 base=Omega Shenron /
    _dummy_s1=Syn Shenron)。1件でも name 不一致なら据置。
  - **★(parallel)兄弟からコピーしない**: 非★カードに ★rarity を焼かない。name一致でも非★兄弟が
    無ければ据置 (only-star)。
  - 複数の非★名前一致兄弟が **異なる rarity** を持つなら曖昧 → 据置。
  - LEADER は非★兄弟が rarity='L'/rarity_ebay='Leader' を持つため、コピーで自動的に 'Leader' 統一。
  「確証なき情報は空欄」= 据置の方が常に安全。据置件数は結果として報告する。
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from datetime import datetime, timezone

DB = "C:/dev/iMak_data/catalog/products.sqlite"
CAT = "dragonball_scg"
TARGET_CT = ("BATTLE", "EXTRA", "LEADER")
SPEC_SOURCE = "dbscg_variant_rarity_nameguard_backfill_20260728"


def _base(pid: str) -> str:
    return re.sub(r"_.*$", "", pid)


def run(apply: bool) -> None:
    conn = sqlite3.connect(DB)
    rows = conn.execute(
        "select id, product_id, name, name_en, specs from products where category=?", (CAT,)
    ).fetchall()
    info = {}
    for rid, pid, name, en, sp in rows:
        d = json.loads(sp)
        info[pid] = dict(id=rid, name=name, en=en, specs=d,
                         rarity=d.get("rarity"), re=d.get("rarity_ebay"),
                         ct=d.get("card_type"))

    targets = [p for p, i in info.items() if i["ct"] in TARGET_CT and not i["rarity"]]
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    upgrade = skip_namemismatch = skip_staronly = skip_ambig = skip_nosib = 0
    from collections import Counter
    fills = Counter()

    for pid in targets:
        me = info[pid]
        b = _base(pid)
        sibs = [(p, info[p]) for p in info
                if _base(p) == b and p != pid and info[p]["rarity"]]
        if not sibs:
            skip_nosib += 1
            continue
        # name-match (name or name_en) siblings
        namematch = [(p, s) for p, s in sibs
                     if s["name"] == me["name"] or (me["en"] and s["en"] == me["en"])]
        if not namematch:
            skip_namemismatch += 1
            continue
        # non-star among name-match
        good = [(p, s) for p, s in namematch if "★" not in str(s["rarity"])]
        if not good:
            skip_staronly += 1
            continue
        rs = {str(s["rarity"]) for p, s in good}
        if len(rs) > 1:
            skip_ambig += 1
            continue
        src_p, src = good[0]
        d = me["specs"]
        d["rarity"] = src["rarity"]
        d["rarity_ebay"] = src["re"] or src["rarity"]
        d["spec_source"] = SPEC_SOURCE
        d["note"] = ((d.get("note", "") + " ") if d.get("note") else "") + (
            f"rarity backfilled from name-matched non-PARA sibling {src_p} "
            "(name-guard, ★除外, KEY/alias 非接触).")
        upgrade += 1
        fills[str(src["rarity"])] += 1
        if apply:
            conn.execute("update products set specs=?, updated_at=? where id=?",
                         (json.dumps(d, ensure_ascii=False), now, me["id"]))
    if apply:
        conn.commit()

    print(f"=== DBSCG variant rarity backfill ({'APPLY' if apply else 'DRY-RUN'}) ===")
    print(f"targets (BATTLE/EXTRA/LEADER rarity欠損): {len(targets)}")
    print(f"  upgrade (name一致・非★・非曖昧):        {upgrade}")
    print(f"  据置 name不一致 (番号分裂疑い):          {skip_namemismatch}")
    print(f"  据置 non-★兄弟なし (★のみ):             {skip_staronly}")
    print(f"  据置 曖昧(複数rarity):                    {skip_ambig}")
    print(f"  据置 rarity持ち兄弟なし:                  {skip_nosib}")
    print(f"  fill rarity 分布: {dict(fills)}")


if __name__ == "__main__":
    run(apply="--apply" in sys.argv)
