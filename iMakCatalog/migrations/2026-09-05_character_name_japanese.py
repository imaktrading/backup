# -*- coding: utf-8 -*-
"""character_name に日本語が入っていた 1,865行を英語に直す (2026-09-05).

判定 (1丁目1番地): **①カタログのデータが誤り**。

## 何が起きていたか

`specs.character_name` は eBay の `C:Character` の元。**英語が入る欄**で、
catalog の 19,723行は `name_en` と同じ英語名を持っている。
ところが 1,865行は **日本語のカード名**が入っていた:

    M4-001  name_en='Weedle'   character_name='ビードル'   ← そのまま出ると C:Character が日本語

出品側は写すだけなので、ここが日本語だと **日本語のまま eBay に出る**。

## 直し方

`name_en` に置き換える (多数派と同じ形)。`name_en` が無い行は触らない (fail-closed)。

★HQ 依頼 `2026-09-04_m3_113_character_features.md` の character 側の答えでもある
  (M3-113 は `メガジガルデex` -> `M Zygarde-ex`)。

実行:
  python migrations/2026-09-05_character_name_japanese.py [--commit]
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
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
SRC = "character_name_en_20260905"
_JA = re.compile(r"[ぁ-んァ-ヶ一-龥]")
CATS = ("pokemon_tcg", "one_piece_tcg", "dragonball_scg", "gundam_tcg")


def run(commit: bool) -> None:
    db = sqlite3.connect(str(api._DB_PATH))
    db.row_factory = sqlite3.Row
    total = skipped = 0
    for cat in CATS:
        rows = db.execute("SELECT id, product_id, name_en, specs FROM products "
                          "WHERE category=?", (cat,)).fetchall()
        fix = []
        for r in rows:
            s = json.loads(r["specs"] or "{}")
            cn = s.get("character_name") or ""
            if not cn or not _JA.search(cn):
                continue
            if not (r["name_en"] or "").strip() or _JA.search(r["name_en"]):
                skipped += 1
                continue                      # 英語名が無ければ触らない
            s["character_name"] = r["name_en"]
            s["character_name_source"] = SRC
            fix.append((r["id"], r["product_id"], cn, r["name_en"], json.dumps(s, ensure_ascii=False)))
        print(f"  {cat:16s} 日本語のまま {len(fix)}行")
        for _id, pid, old, new, _ in fix[:4]:
            print(f"      {pid:14s} {old!r} -> {new!r}")
        if commit:
            for i, (_id, _pid, _o, _n, sp) in enumerate(fix, 1):
                db.execute("UPDATE products SET specs=?, updated_at=? WHERE id=?", (sp, NOW, _id))
                if i % 200 == 0:              # 途中保存
                    db.commit()
            db.commit()
        total += len(fix)
    db.close()
    print("")
    print(f"{'適用' if commit else '(dry-run — --commit で適用)'} {total} 行 "
          f"/ 英語名が無くて触らなかった {skipped} 行")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    run(ap.parse_args().commit)


if __name__ == "__main__":
    main()
