# -*- coding: utf-8 -*-
"""UT の画像URLを一番大きい形に差し替える (2026-09-09).

判定 (1丁目1番地): **①カタログのデータ**。小さい絵を持っていた。

## 実測

    そのまま                      1500 x 2000
    ?impolicy=quality             **2100 x 2800**   ← これが上限
    ?width=3000 / 4000 / 6000     2100 x 2800 (幅を上げても変わらない)

main / sub / feature とも同じ。**色チップ (chip) は 100x100 のまま**なので付けない
(容量だけ6倍になる)。

ユーザー指示 (2026-09-09):「画像も出来るだけ大きくてきれいなやつね」。

実行:
  python migrations/2026-09-09_ut_images_to_large.py
  python migrations/2026-09-09_ut_images_to_large.py --commit
"""
from __future__ import annotations

import argparse
import json
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
BIG = "?impolicy=quality"


def big(u: str) -> str:
    if not u or "?" in u or "/chip/" in u:
        return u
    return u + BIG


def run(commit: bool) -> None:
    db = sqlite3.connect(str(api._DB_PATH), timeout=120)
    db.row_factory = sqlite3.Row
    rows = db.execute("SELECT id, product_id, images, specs FROM products "
                      "WHERE category='uniqlo_ut'").fetchall()
    changed = n_img = 0
    for r in rows:
        imgs = json.loads(r["images"] or "[]")
        s = json.loads(r["specs"] or "{}")
        new = [big(u) for u in imgs]
        new_iu = [big(u) for u in (s.get("image_urls") or [])]
        if new == imgs and new_iu == (s.get("image_urls") or []):
            continue
        changed += 1
        n_img += sum(1 for a, b in zip(imgs, new) if a != b)
        if commit:
            s["image_urls"] = new_iu
            db.execute("UPDATE products SET images=?, specs=?, updated_at=? WHERE id=?",
                       (json.dumps(new, ensure_ascii=False),
                        json.dumps(s, ensure_ascii=False), NOW, r["id"]))
            if changed % 200 == 0:            # 途中保存
                db.commit()
    if commit:
        db.commit()
    db.close()
    print(f"=== UT 画像を大きい形に ({'APPLY' if commit else 'DRY-RUN'}) ===")
    print(f"  {changed}行 / 画像 {n_img}枚 を 2100x2800 の形にした")
    print("")
    print(f"{'適用' if commit else '(dry-run — --commit で適用)'}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    run(ap.parse_args().commit)


if __name__ == "__main__":
    main()
