# -*- coding: utf-8 -*-
"""多変種カードに付いた「番号未確認」候補を cache から落とす (2026-09-20).

`mercari_psa_resource.should_offer_loose()` で **これから**は出なくなったが、
**既に cache に焼かれた分は残る**。実測 2026-09-20: 83出品 / 392本 が残っており、
目視画面に毎日出ていた (ユーザー指摘「何十回も出てくる」)。

決定を変えたら、前の決定で書いた分をその場で洗い直す (グローバル規約 追記⑤)。
同じことがまた起きたら、これを流せば 0件にできる。

    python purge_loose_on_multivariant.py --dry     # 件数だけ
    python purge_loose_on_multivariant.py --commit  # 実際に消す (控えを取る)
"""
from __future__ import annotations

import json
import os
import shutil
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

CACHE = os.path.join(_HERE, "psa_research_cache.json")


def targets(cache, keymap, mp, hoju):
    """落とす対象 [(itemID, 本数)] (純関数・I/O は引数)。"""
    out = []
    for iid, v in (cache or {}).items():
        loose = ((v or {}).get("mercari") or {}).get("loose_cands") or []
        if not loose:
            continue
        key = keymap.get(iid) or ""
        cno = hoju._card_no_from_key(key) if key else ""
        if not cno:
            continue
        try:
            cat = mp.split_key(key)[0]
        except Exception:                                      # noqa: BLE001
            cat = ""
        if mp._is_multi_variant(cno, cat):
            out.append((iid, len(loose)))
    return out


def main():
    import mercari_psa_resource as mp
    import psa_hoju_fill as hoju
    from sheet_io import product_index

    keymap = product_index()[0]
    with open(CACHE, encoding="utf-8") as f:
        cache = json.load(f)
    tg = targets(cache, keymap, mp, hoju)
    print("多変種なのに番号未確認候補を持つ出品: %d件 / 候補 %d本"
          % (len(tg), sum(n for _, n in tg)))
    if "--commit" not in sys.argv:
        print("(--commit で実際に消します)")
        return 0
    shutil.copy(CACHE, CACHE + ".bak_pre_loose_purge")
    for iid, _ in tg:
        cache[iid]["mercari"]["loose_cands"] = []
    with open(CACHE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False)
    print("消しました。残り0件。控え: %s" % (CACHE + ".bak_pre_loose_purge"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
