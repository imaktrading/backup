"""取り込みで入った `011/XY-P` 形の product_id を catalog の書き方に直す (2026-09-04).

判定 (1丁目1番地): **①カタログのデータが誤り** → catalog 側で直す。

## 何が起きたか

2026-09-04 のポケモン取り込み (807枚) で、プロモの一部が **券面の印字そのまま**の
`011/XY-P` / `133/M-P` という product_id で入った。catalog の書き方は `XYP-011` /
`M-P-133` なので、**同じカードが2つの ID で並ぶ**。出品くしは ID 完全一致で引くので、
引けない・重複する・変換表も当たらない。

## やること

1. 画像フォルダ (`.../large/XY-P/...`) が同じ既存行から **正しい書き方**を学ぶ
   (フォルダ → ID の頭。`XY-P` → `XYP` / `M-P` → `M-P`)
2. 直した ID が既に在れば **新しい方を消す** (既存が正。13件が該当)
3. 無ければ改名する (34件)

★推測で書き方を決めない。既存行から学ぶ。学べなければ触らない (fail-closed)。

実行:
  python migrations/2026-09-04_pokemon_slash_ids.py
  python migrations/2026-09-04_pokemon_slash_ids.py --commit
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
CAT = "pokemon_tcg"


def _folder(images: str | None) -> str:
    for u in json.loads(images or "[]"):
        m = re.search(r"/large/([^/]+)/", str(u))
        if m:
            return m.group(1)
    return ""


def run(commit: bool) -> None:
    db = sqlite3.connect(Path(api._DB_PATH))
    db.row_factory = sqlite3.Row
    # 画像フォルダ → 既存 ID の頭 (最頻)
    pref: dict[str, Counter] = {}
    for r in db.execute("SELECT product_id, images FROM products WHERE category=? "
                        "AND product_id NOT LIKE '%/%'", (CAT,)):
        f = _folder(r["images"])
        pid = r["product_id"] or ""
        if f and "-" in pid:
            pref.setdefault(f, Counter())[pid.rsplit("-", 1)[0]] += 1
    learned = {k: v.most_common(1)[0][0] for k, v in pref.items()}

    rows = db.execute("SELECT id, product_id, name, images FROM products "
                      "WHERE category=? AND product_id LIKE '%/%'", (CAT,)).fetchall()
    ren, dele, skip = [], [], []
    for r in rows:
        num = (r["product_id"] or "").split("/")[0]
        head = learned.get(_folder(r["images"]))
        if not head or not num.isdigit():
            skip.append(r["product_id"])
            continue
        new = f"{head}-{num}"
        ex = db.execute("SELECT 1 FROM products WHERE category=? AND product_id=?",
                        (CAT, new)).fetchone()
        (dele if ex else ren).append((r["id"], r["product_id"], new, r["name"]))

    print(f"=== `NNN/XX-P` 形の整理 ({'APPLY' if commit else 'DRY-RUN'}) ===")
    print(f"  改名 {len(ren)} / 重複削除 {len(dele)} / 触らない {len(skip)}")
    for _, old, new, nm in ren[:5]:
        print(f"    改名  {old:12s} -> {new:12s} {nm}")
    for _, old, new, nm in dele[:5]:
        print(f"    削除  {old:12s} (既存 {new} と同じ) {nm}")
    if skip:
        print(f"    触らない: {skip}")

    if commit:
        for _id, _old, new, _nm in ren:
            db.execute("UPDATE products SET product_id=?, updated_at=? WHERE id=?",
                       (new, NOW, _id))
        for _id, _old, _new, _nm in dele:
            db.execute("DELETE FROM products WHERE id=?", (_id,))
        db.commit()
        print("\n適用")
    else:
        print("\n(dry-run — --commit で適用)")
    db.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--commit", action="store_true")
    run(p.parse_args().commit)
