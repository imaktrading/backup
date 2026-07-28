"""Gundam variant rarity 欠損の name-guard backfill — 2026-07-28

依頼: requests/2026-07-28_listed_psa_field_gaps.md (出品中 gundam の C:Rarity 欠損)。
DBSCG (scripts/backfill_dbscg_variant_rarity_20260728.py) と同方式。

gundam rarity 欠損 294件のうち、**同base・名前一致・非★の rarity 持ち兄弟**がある分だけ
rarity + rarity_ebay をコピー (= 公式(bandai API のレアリティ)由来分。推測でない)。
名前不一致 / ★のみ / 兄弟に rarity 無し は据置 (公式に取れない=空欄が正)。
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone

DB = "C:/dev/iMak_data/catalog/products.sqlite"
CAT = "gundam_tcg"
SPEC_SOURCE = "gundam_variant_rarity_nameguard_backfill_20260728"


def _base(pid: str) -> str:
    return re.sub(r"_.*$", "", pid)


def _rarity(d: dict):
    return d.get("rarity") or d.get("Rarity")


def run(apply: bool) -> None:
    conn = sqlite3.connect(DB)
    rows = conn.execute(
        "select id, product_id, name, name_en, specs from products where category=?", (CAT,)
    ).fetchall()
    info = {}
    for rid, pid, name, en, sp in rows:
        d = json.loads(sp)
        info[pid] = dict(id=rid, name=name, en=en, specs=d, rarity=_rarity(d))

    targets = [p for p, i in info.items() if not i["rarity"]]
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    upgrade = skip_namemismatch = skip_staronly = skip_ambig = skip_nosib = 0
    fills = Counter()

    for pid in targets:
        me = info[pid]
        b = _base(pid)
        sibs = [(p, info[p]) for p in info if _base(p) == b and p != pid and info[p]["rarity"]]
        if not sibs:
            skip_nosib += 1
            continue
        namematch = [(p, s) for p, s in sibs
                     if s["name"] == me["name"] or (me["en"] and s["en"] == me["en"])]
        if not namematch:
            skip_namemismatch += 1
            continue
        # ★(DBSCG) と + (Gundam: SPLR+/R+/LR+ 等) は parallel マーカー → コピー元から除外。
        #   非parallel カードに parallel rarity を焼かない (2026-07-28: 当初 + を見落として
        #   GD01-002_p3=SPLR+ 等 2件を誤 backfill → 即据置に是正した経緯)。
        good = [(p, s) for p, s in namematch
                if "★" not in str(s["rarity"]) and "+" not in str(s["rarity"])]
        if not good:
            skip_staronly += 1
            continue
        rs = {str(s["rarity"]) for p, s in good}
        if len(rs) > 1:
            skip_ambig += 1
            continue
        src_p, src = good[0]
        sd = src["specs"]
        d = me["specs"]
        d["rarity"] = src["rarity"]
        d["rarity_ebay"] = sd.get("rarity_ebay") or src["rarity"]
        d["spec_source"] = SPEC_SOURCE
        d["note"] = ((d.get("note", "") + " ") if d.get("note") else "") + (
            f"rarity backfilled from name-matched non-PARA sibling {src_p} (name-guard, ★除外).")
        upgrade += 1
        fills[str(src["rarity"])] += 1
        if apply:
            conn.execute("update products set specs=?, updated_at=? where id=?",
                         (json.dumps(d, ensure_ascii=False), now, me["id"]))
    if apply:
        conn.commit()

    print(f"=== Gundam variant rarity backfill ({'APPLY' if apply else 'DRY-RUN'}) ===")
    print(f"targets (rarity欠損): {len(targets)}")
    print(f"  upgrade: {upgrade}")
    print(f"  据置 name不一致: {skip_namemismatch}")
    print(f"  据置 ★のみ: {skip_staronly}")
    print(f"  据置 曖昧: {skip_ambig}")
    print(f"  据置 rarity兄弟なし(公式に取れない): {skip_nosib}")
    print(f"  fill: {dict(fills)}")


if __name__ == "__main__":
    run(apply="--apply" in sys.argv)
