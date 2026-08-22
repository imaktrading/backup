#!/usr/bin/env python3
"""ポケモンのタイプを生HTMLから読み直す (取り直し不要・手元のファイルだけ).

2026-08-23。**倉庫に残した生HTMLの最初の出番**。ネットに1回も行かずに直せる。

## 何が誤っていたか (実測)
`type_en` の分布に **Lightning / Darkness / Metal / Colorless が1件も無く**、
代わりに Fighting が 6,138件あった。ピカチュウ (雷) が Fighting になっていた。

原因は取り込み側の2つの誤り:
  ① 公式のクラス名は `icon-electric` / `icon-dark` / `icon-steel` / `icon-none` で、
     探していた lightning / darkness / metal / colorless は **存在しない**
  ② HTML 全体から最初に当たったアイコンを採っていたので、タイプが読めない時に
     **弱点のアイコン**を拾っていた (ピカチュウの弱点=闘)

## 直し方
生HTML の `<span class="hp-type">タイプ</span>` の**直後**のアイコンから読み直す。
タイプ欄が無いカード (トレーナーズ / エネルギー) は **空にする** (前の誤った値を消す)。

実行:
  python migrations/2026-08-23_pokemon_type_reparse.py           # dry-run
  python migrations/2026-08-23_pokemon_type_reparse.py --commit
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
from pokemon_tcg import _TYPE_CLASS_TO_EN, _EN_TO_JP_TYPE  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

NOW = datetime.now().isoformat(timespec="seconds")
SOURCE = "type_reparse_from_raw_20260823"
RE_TYPE = re.compile(r'hp-type">\s*タイプ\s*</span>\s*<span class="icon-([a-z]+)')
RE_CID = re.compile(r"/card/(\d+)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()
    db = sqlite3.connect(api._DB_PATH, timeout=120)
    db.row_factory = sqlite3.Row
    n, updates, noraw = Counter(), [], 0
    for r in db.execute("SELECT id, product_id, source_url, specs FROM products "
                        "WHERE category='pokemon_tcg'"):
        m = RE_CID.search(r["source_url"] or "")
        if not m:
            continue
        html = _raw_store.load("pokemon_tcg", m.group(1))
        if not html:
            noraw += 1
            continue
        s = json.loads(r["specs"] or "{}")
        cur = s.get("type_en")
        mt = RE_TYPE.search(html)
        new = _TYPE_CLASS_TO_EN.get(mt.group(1)) if mt else None
        if new == cur:
            continue
        if new:
            s["type_en"] = new
            s["type_jp"] = _EN_TO_JP_TYPE.get(new, "")
            n[f"{cur or '(空)'} -> {new}"] += 1
        else:
            s.pop("type_en", None)
            s.pop("type_jp", None)
            n[f"{cur} -> (空欄。タイプ欄が無いカード)"] += 1
        s["type_source"] = SOURCE
        updates.append((json.dumps(s, ensure_ascii=False), NOW, r["id"]))
    print("=== タイプの読み直し (%s) ===" % ("APPLY" if args.commit else "DRY-RUN"))
    print(f"  直す {len(updates)} 行 / 生HTMLが無い {noraw} 行")
    for k, v in n.most_common(18):
        print(f"    {k:44s} {v}")
    if args.commit and updates:
        db.executemany("UPDATE products SET specs=?, updated_at=? WHERE id=?", updates)
        db.commit()
        print("[OK] 適用 %d 行" % len(updates))
    elif not args.commit:
        print("(dry-run — --commit で適用)")
    db.close()


if __name__ == "__main__":
    main()
