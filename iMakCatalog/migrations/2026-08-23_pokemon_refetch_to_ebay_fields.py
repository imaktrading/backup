#!/usr/bin/env python3
"""取り直しで入った生値を eBay 用の項目に落とす (ポケモン).

2026-08-23。8/22 の公式取り直し (21,982枚 / 失敗0) で入った生値:
    type_en 11,637 / attack_damage 6,186 / hp / stage / regulation_set 15,679 …
決定表 (`_contract_aspects.yaml`) の source は `*_ebay` 側なので、そこへ落とす。

| 生値 | 行き先 | 根拠 |
|---|---|---|
| `type_en` (Grass/Fire/…) | `color_ebay` (eBay: Attribute/MTG:Color) | 11タイプとも eBay の27値に実在 |
| `attack_damage` | `attack_power_ebay` (自由入力) | ワザのダメージ |
| `hp` | `hp_ebay` (自由入力) | |

## 落とさないもの
- `stage` の **基本 / VMAX / VSTAR** … eBay の Stage 9値 (Basic/Stage 1/Stage 2/Mega/…) に
  該当が無い。`たね→Basic` `1進化→Stage 1` `2進化→Stage 2` `MEGA→Mega` は既に入っている
- `regulation_set` … eBay に項目が無い。社内用 (収録弾の特定に使う)

実行:
  python migrations/2026-08-23_pokemon_refetch_to_ebay_fields.py           # dry-run
  python migrations/2026-08-23_pokemon_refetch_to_ebay_fields.py --commit
"""
from __future__ import annotations

import argparse
import json
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
SOURCE = "refetch_to_ebay_20260823"
MASTER = Path(r"C:\dev\iMak_data\catalog\_input\ebay_aspects_183454_latest.json")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()
    A = json.loads(MASTER.read_text(encoding="utf-8"))["aspects"]
    ATTR = set(A["Attribute/MTG:Color"]["all"])
    db = sqlite3.connect(api._DB_PATH, timeout=120)
    db.row_factory = sqlite3.Row
    n, skip, updates = Counter(), Counter(), []
    for r in db.execute("SELECT id, specs FROM products WHERE category='pokemon_tcg'"):
        s = json.loads(r["specs"] or "{}")
        touched = False
        t = (s.get("type_en") or "").strip()
        if t and not (s.get("color_ebay") or "").strip():
            if t in ATTR:
                s["color_ebay"] = t
                n[f"Attribute={t}"] += 1
                touched = True
            else:
                skip[f"eBay の Attribute に無い: {t}"] += 1
        d = str(s.get("attack_damage") or "").strip()
        if d and not str(s.get("attack_power_ebay") or "").strip():
            s["attack_power_ebay"] = d
            n["Attack/Power"] += 1
            touched = True
        h = str(s.get("hp") or "").strip()
        if h and not str(s.get("hp_ebay") or "").strip():
            s["hp_ebay"] = h
            n["HP"] += 1
            touched = True
        if touched:
            s["refetch_to_ebay_source"] = SOURCE
            updates.append((json.dumps(s, ensure_ascii=False), NOW, r["id"]))
    print("=== 取り直しの生値を eBay 項目へ (%s) ===" % ("APPLY" if args.commit else "DRY-RUN"))
    print("  触る行 %d" % len(updates))
    for k, v in n.most_common(16):
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
