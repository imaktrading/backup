# -*- coding: utf-8 -*-
"""ワンピの収録商品名を公式に合わせる (2026-09-05).

判定 (1丁目1番地): **①カタログのデータが誤り**。公式 (onepiece-cardgame.com) を
今その場で取り直し、**公式の枝番つき id** (`OP10-022_p2` 等) で1対1に突き合わせた。

## 直す3つ

1. **EB-04 のカードが OP-15 の名前になっていた (41行)**
   公式: `エクストラブースター EGGHEAD CRISIS【EB-04】`
   catalog: `BOOSTER PACK -ADVENTURE ON KAMI’S ISLAND- [OP15-EB04]` / Set=`Adventure on Kami's Island`
   **別の商品名で出品していた** = 誤記載。同じ弾の他の 40行は既に `Egghead Crisis` で
   入っており、そちらに揃える (eBay に在る値なので①)。

2. **汎用ラベルのままだった promo (115行)**
   `プロモーションカード` / `Promotion Card` / `限定商品収録カード` を、
   公式の配布商品名 (`交流会 2025年7月開催記念品` 等 65商品) に置き換える。
   ★eBay に出る値は **変わらない** (65商品すべて `Promo Cards`)。
     変わるのは出所の記録と、PSA ラベルとの突き合わせ精度
     (`_op_edition_matches` が商品名で刷りを選び分けられるようになる)。

3. **個別2件** — `OP13-001_p1` は一番くじ購入者特典、`P-001` はプロモパック2022。

## 触らないもの

日本語名と英語名の違いだけのもの (`ブースターパック 世界最強の戦士【OP-17】` ↔
`BOOSTER PACK -THE WORLD’S STRONGEST WARRIORS- [OP-17]`、297行) は**同じ商品**。
名前の書き方が違うだけなので直さない。

実行:
  python migrations/2026-09-05_op_setname_from_official.py [--commit]
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import api  # noqa: E402
import official_drift_check as O  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

NOW = datetime.now().isoformat(timespec="seconds")
SRC = "official_setname_20260905"
SERIES = ["550901", "550801", "550204", "550115", "550117"]
GENERIC = {"プロモーションカード", "Promotion Card", "Other Product Card", "限定商品収録カード"}
EB04 = ("エクストラブースター EGGHEAD CRISIS【EB-04】", "Egghead Crisis")


def official_pairs() -> dict:
    """公式の {枝番つき id: 収録商品名}."""
    out = {}
    for sid in SERIES:
        page = O._get(O.LIST_URL.format(sid=sid))
        for b in re.split(r'(?=<dl class="modalCol")', page)[1:]:
            mid = re.search(r'<dl class="modalCol" id="([^"]+)"', b)
            mget = re.search(r'class="getInfo"><h3>[^<]*</h3>(.*?)</div>', b, re.S)
            if mid and mget:
                out[mid.group(1)] = O._norm(re.sub(r"<[^>]+>", " ", mget.group(1)))
    return out


def run(commit: bool) -> None:
    pairs = official_pairs()
    db = sqlite3.connect(str(api._DB_PATH))
    db.row_factory = sqlite3.Row
    fix, products = [], Counter()
    for pid, want in pairs.items():
        r = db.execute("SELECT id, product_id, set_name_official, specs FROM products "
                       "WHERE category='one_piece_tcg' AND product_id=?", (pid,)).fetchone()
        if r is None:
            continue
        cur = (r["set_name_official"] or "").strip()
        if O._norm(cur) == want:
            continue
        ebay = None
        if "EB-04" in want and "EGGHEAD" in want.upper():
            want, ebay = EB04                      # ① eBay に在る値に揃える
        elif cur not in GENERIC:
            continue                               # 日本語/英語の書き方違い → 触らない
        fix.append((r["id"], pid, cur, want, ebay))
        products[want] += 1

    print(f"=== 収録商品名を公式に合わせる ({'APPLY' if commit else 'DRY-RUN'}) — {len(fix)}行 ===")
    for k, v in products.most_common(10):
        print(f"    {v:4d}行  {k}")
    done = 0
    if commit:
        for _id, _pid, _cur, want, ebay in fix:
            if ebay:
                sp = json.loads(db.execute("SELECT specs FROM products WHERE id=?",
                                           (_id,)).fetchone()[0] or "{}")
                sp["set_name_ebay"] = ebay
                sp["set_name_ebay_source"] = SRC
                db.execute("UPDATE products SET specs=? WHERE id=?",
                           (json.dumps(sp, ensure_ascii=False), _id))
            db.execute("UPDATE products SET set_name=?, set_name_official=?, updated_at=? "
                       "WHERE id=?", (want, want, NOW, _id))
            done += 1
            if done % 50 == 0:                     # 途中保存
                db.commit()
        db.commit()
    db.close()
    print("")
    print(f"{'適用' if commit else '(dry-run — --commit で適用)'} {len(fix)} 行")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    run(ap.parse_args().commit)


if __name__ == "__main__":
    main()
