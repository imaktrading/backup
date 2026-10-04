#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""補URL の控え (psa_research_cache.json) に貯まったメルカリ候補を、今そのまま買えるか API で洗い直す (2026-10-04)。

★4回目の「補URL③に AUC (オークション) が出ている」。10/1 に API 検索へ切り替えた時、補URL の夜探しの
  検索だけオークションを落としておらず、検索結果の候補 (all_cands / loose / 版未確認) が詳細を開かずに
  控えに貯まって目視に出ていた。入口は直した (mercari_psa_resource.is_api_auction)。
  これは **もう貯まっている分** を洗う一度きりの道具: 買えない (オークション・売り切れ・消えた) と
  確かめた個人出品は「買えない台帳」(not_buyable_urls.json) に入れる。目視の画面はこの台帳で落とす。

  - 個人の出品 (/item/m…) だけ。Shops は再入荷するので入れない
  - 確かめられなかった物は入れない (判定不能は外さない)

    python cache_buyable_sweep.py            # 数えるだけ
    python cache_buyable_sweep.py --write    # 台帳に入れる
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
CACHE = os.path.join(HERE, "psa_research_cache.json")
KINDS = ("best", "cands", "all_cands", "loose_cands", "variant_cands")


def cache_item_urls(cache):
    """控え → 個人出品のメルカリ URL の集合 (純関数)。"""
    out = set()
    for e in (cache or {}).values():
        m = (e or {}).get("mercari") if isinstance(e, dict) else None
        if not isinstance(m, dict):
            continue
        for k in KINDS:
            v = m.get(k)
            for t in ([v] if k == "best" else (v or [])):
                if isinstance(t, (list, tuple)) and len(t) > 1 and "jp.mercari.com/item/" in str(t[1]):
                    out.add(t[1])
    return out


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    write = "--write" in argv
    import mercari_psa_resource as mp
    with open(CACHE, encoding="utf-8") as f:
        cache = json.load(f)
    urls = sorted(cache_item_urls(cache) - set(mp.load_not_buyable() or {}))
    print(f"控えの個人出品 (台帳に無い分) {len(urls)}本 を確かめます", flush=True)
    bad = unknown = 0
    step = 200
    for i in range(0, len(urls), step):
        part = urls[i:i + step]
        ok, _t, unk = mp.api_stock_check(part)
        unknown += len(unk)
        for u, v in ok.items():
            if v is False:
                bad += 1
                if write:
                    mp.remember_not_buyable(u, "オークション/売り切れ (控えの洗い直し 2026-10-04)")
        print(f"  {min(i + step, len(urls))}/{len(urls)} — 買えない {bad} / 確かめられず {unknown}", flush=True)
    print(f"{'✅ 台帳に入れた' if write else '(数えただけ・--write で台帳に入れる)'}: 買えない {bad}本 "
          f"/ 確かめられず {unknown}本 (入れない)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
