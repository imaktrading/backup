#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""補URL の **目視待ち**。機械が勝手にシートへ書かず、ここに積む (2026-09-08 ユーザー指示)。

■ なぜ
2026-09-08 に「補URLが別のカードで、そのぶん安く出品されていた」事故が3件出た
(820026248229 $155.98/正 $405.98・820049712142 $202.98/正 $648.98・358908083352)。
3件ともバイヤーの問い合わせやオファーで発覚。どこから入ったかログから特定できず、
ユーザー判断:

    「勝手に補に追加するルートは閉じて、必ず目視を通る様にして」

■ 何が危ないのか (自動経路が悪意なく間違う仕組み)
自動の2経路は **KEY (版まで含んだ product_id) が一致する行**から URL を配る。理屈は正しいが、
**元の行の KEY が誤っていれば、誤った版の URL をそのまま配る**。KEY の取り違えは実在した
(2026-09-07: `P-033` と `OP07-033_p2`)。しかも同じ番号の別版は、商品名では見分けが付かない
(ST10-006 は版が8つあり全部 SR)。だから機械の一致だけで書き込ませない。

■ 使い方
書きたかった内容を `queue()` で積み、人が目視で採否を決める。
    python aux_pending.py            # 溜まっている件数と中身
"""
from __future__ import annotations

import datetime
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "..", "review_logs", "aux_url_pending.jsonl")


def build_rows(row_to_urls, source, existing_by_row=None, item_of=None, today=None):
    """積む行を作る (純関数)。**既にシートに在る URL は積まない** (二度見せない)。"""
    today = today or datetime.date.today().isoformat()
    out = []
    for row, urls in (row_to_urls or {}).items():
        have = {(u or "").strip() for u in (existing_by_row or {}).get(row, []) if u}
        for u in (urls or []):
            u = (u or "").strip()
            if not u or u in have:
                continue
            out.append({"date": today, "source": source, "row": row,
                        "itemID": (item_of or {}).get(row, ""), "url": u})
    return out


def queue(row_to_urls, source, existing_by_row=None, item_of=None, path=None):
    """目視待ちに積む (I/O)。戻り: 積んだ本数。"""
    rows = build_rows(row_to_urls, source, existing_by_row, item_of)
    if not rows:
        return 0
    p = path or PATH
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return len(rows)


def load(path=None):
    p = path or PATH
    out = []
    if not os.path.exists(p):
        return out
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:                                  # noqa: BLE001
                continue
    return out


if __name__ == "__main__":
    import collections
    import io
    import sys
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    rows = load()
    print(f"補URL 目視待ち: {len(rows)}本")
    for src, n in collections.Counter(r.get("source") for r in rows).most_common():
        print(f"  {src}: {n}本")
    for r in rows[-10:]:
        print(f"  {r.get('date')} row{r.get('row')} {r.get('itemID')} {r.get('url')[:60]}")
