#!/usr/bin/env python3
"""別のセットの名前が入っている行を焼き直す (HQ 依頼 2026-08-22 / 322枚).

`specs.set_name_ebay` に **別セットの eBay 値** が入っていた:

    SV4K-*  拡張パック「古代の咆哮」   -> 'Sv5k: Wild Force'      (SV5K の名前)  95枚
    SV4M-*  拡張パック「未来の一閃」   -> 'Sv5m: Cyber Judge'     (SV5M の名前)  95枚
    SV9-*   拡張パック「バトルパートナーズ」 -> 'Sv09: Journey Together' (英語版の別セット) 132枚

種は `ebay_filter_map` の3行が1行ずつずれていたこと (SV4K->Wild Force 等)。
変換表は 2026-08-22 に是正済み。ここは products に焼いてある値を直す。

## なぜ通常の restamp では直らないか
`Sv5k: Wild Force` は **eBay の一覧に実在する値**なので、restamp の「格下げ禁止ガード」
(今の値が一覧に在るなら触らない) が働いて素通りする。**別セットの実在値**という
種類の誤りはガードで守れない。だから専用に直す。

## 検出条件 (HQ 提供・そのまま採用)
Sv世代の eBay 値の接頭辞は JP セットコードなので、商品の product_id 接頭辞と一致するはず。
    ^(Sv[0-9][0-9A-Za-z]*)\s*: の接頭辞 != product_id の頭 → 矛盾
実行時に pokemon 全件へ当てて、ヒットした行だけ derive し直す。

実行:
  python migrations/2026-08-22_fix_wrong_set_prefix_322.py           # dry-run
  python migrations/2026-08-22_fix_wrong_set_prefix_322.py --commit
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
import api  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

NOW = datetime.now().isoformat(timespec="seconds")
SOURCE = "fix_wrong_set_prefix_20260822"
PREFIX_RE = re.compile(r"^(Sv[0-9][0-9A-Za-z]*)\s*:")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()
    db = sqlite3.connect(api._DB_PATH, timeout=120)
    db.row_factory = sqlite3.Row
    pairs, updates, unresolved = Counter(), [], Counter()
    for r in db.execute("SELECT id, product_id, set_name_official, specs FROM products "
                        "WHERE category='pokemon_tcg'"):
        s = json.loads(r["specs"] or "{}")
        cur = s.get("set_name_ebay") or ""
        m = PREFIX_RE.match(cur)
        if not m:
            continue
        head = str(r["product_id"]).split("-")[0]
        if m.group(1).upper() == head.upper():
            continue
        new = api.derive_set_name_ebay("pokemon_tcg", r["set_name_official"], r["product_id"])
        if not new or new == cur:
            unresolved[f"{head}: {cur}"] += 1
            continue
        pairs[(cur, new)] += 1
        s["set_name_ebay"] = new
        s["set_name_ebay_source"] = SOURCE
        updates.append((json.dumps(s, ensure_ascii=False), NOW, r["id"]))
    print("=== 別セット名の焼き直し (%s) ===" % ("APPLY" if args.commit else "DRY-RUN"))
    print("  直す %d 行" % len(updates))
    for (a, b), n in pairs.most_common():
        print(f"    {a:26s} -> {b:26s} {n}")
    if unresolved:
        print("  直せなかった (変換表に無い):", unresolved.most_common(5))
    if args.commit and updates:
        db.executemany("UPDATE products SET specs=?, updated_at=? WHERE id=?", updates)
        db.commit()
        print("[OK] 適用 %d 行" % len(updates))
    elif not args.commit:
        print("(dry-run — --commit で適用)")
    db.close()


if __name__ == "__main__":
    main()
