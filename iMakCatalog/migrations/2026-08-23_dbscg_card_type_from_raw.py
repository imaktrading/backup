#!/usr/bin/env python3
"""DBSCG の card_type を生JSONから埋める (取り直し不要).

2026-08-23。DBSCG だけ `card_type_ebay` が 50% で止まっていた。残り 2,754行は
**生の card_type も持っていない** 行 (パラレル等)。8/22 に保存した生JSONを見ると
`Type` が入っているので、そこから埋める。ネットには行かない。

  生JSON `card_config` の `Type` (Leader / Battle / Extra / Unison …)
    -> specs.card_type (公式の生値・大文字)
    -> specs.card_type_ebay (eBay は自由入力なので公式の呼び方の英語表記)

## 守ること
- 既に値がある行は触らない
- 生JSON が手元に無い行は触らない (1行だけ該当)
- `Type` 以外の項目 (Rarity / Color / Power) は **今回は触らない**。
  パラレルの rarity は `L★` のように刷り違いマーカー付きで、既存の正規化と
  ぶつかるため別途 (ここで混ぜない)

実行:
  python migrations/2026-08-23_dbscg_card_type_from_raw.py           # dry-run
  python migrations/2026-08-23_dbscg_card_type_from_raw.py --commit
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
sys.path.insert(0, str(ROOT / "scrapers"))
import api  # noqa: E402
import _raw_store  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

NOW = datetime.now().isoformat(timespec="seconds")
SOURCE = "dbscg_card_type_from_raw_20260823"
RE_CID = re.compile(r"/card/(\d+)")
# 生JSON の Type -> eBay に出す表記 (自由入力。公式の呼び方の英語表記)
EBAY = {"leader": "Leader", "battle": "Battle", "extra": "Extra",
        "unison": "Unison", "energy marker": "Energy Marker",
        # 生JSON が日本語版のことがある (JA 取得分)。公式の呼び方の英語表記へ。
        "リーダー": "Leader", "バトル": "Battle", "エクストラ": "Extra",
        "ユニゾン": "Unison", "エナジーマーカー": "Energy Marker"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()
    db = sqlite3.connect(api._DB_PATH, timeout=120)
    db.row_factory = sqlite3.Row
    n, skip, updates = Counter(), Counter(), []
    for r in db.execute("SELECT id, product_id, source_url, specs FROM products "
                        "WHERE category='dragonball_scg'"):
        s = json.loads(r["specs"] or "{}")
        if str(s.get("card_type") or "").strip():
            continue
        m = RE_CID.search(r["source_url"] or "")
        raw = _raw_store.load("dragonball_scg", m.group(1), ext="json") if m else None
        if not raw:
            skip["生JSONが手元に無い"] += 1
            continue
        try:
            cfg = json.loads(raw)["success"]["card"]["card_config"]
        except Exception:
            skip["生JSONを読めない"] += 1
            continue
        t = next((c.get("value") for c in cfg
                  if c.get("config_name") in ("Type", "カード種類") and c.get("value")), None)
        if not t:
            skip["生JSONに Type が無い"] += 1
            continue
        ev = EBAY.get(t.strip().lower())
        # 生値は英語で持つ (日本語版JSONでも公式の英語表記に揃える)
        s["card_type"] = (ev or t).upper()
        if ev:
            s["card_type_ebay"] = ev
            n[f"card_type_ebay={ev}"] += 1
        else:
            skip[f"表に無い Type: {t}"] += 1
        s["card_type_source"] = SOURCE
        updates.append((json.dumps(s, ensure_ascii=False), NOW, r["id"]))
    print("=== DBSCG card_type を生JSONから (%s) ===" % ("APPLY" if args.commit else "DRY-RUN"))
    print("  触る行 %d" % len(updates))
    for k, v in n.most_common():
        print(f"    {k:34s} {v}")
    if skip:
        print("  見送り:", skip.most_common(5))
    if args.commit and updates:
        db.executemany("UPDATE products SET specs=?, updated_at=? WHERE id=?", updates)
        db.commit()
        print("[OK] 適用 %d 行" % len(updates))
    elif not args.commit:
        print("(dry-run — --commit で適用)")
    db.close()


if __name__ == "__main__":
    main()
