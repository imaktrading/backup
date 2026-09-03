"""文字の分解形 (NFD) を NFC に揃える (2026-09-04).

判定 (1丁目1番地): **①カタログのデータが誤り** → catalog 側で直す。

## 何が起きたか

ポケモンの新規取り込み (2026-09-04 / 807枚) で、`set_name_official` が **分解形**で
入った。見た目は同じでも中身が違う:

    ジ = U+30B8            (合成形 NFC。既存の行はこちら)
    ジ = U+30B7 + U+3099   (分解形 NFD。シ + 濁点。新しく入った行はこちら)

変換表は文字列の完全一致で引くので、**分解形の行は永久に引けない**。
実際 `拡張パック「アビスアイ」` 等 224行が Set 空欄のまま残っていた。
`in` 判定も外れるので、探しても「見つからない」ように見える。

## やること

`name` / `name_jp` / `set_name_official` を NFC に揃える (241箇所)。
値の意味は変わらない (同じ文字の書き方を1つに寄せるだけ)。

★再発防止は `api.upsert()` 側 (取り込み口) で NFC 化する。ここは既存分の掃除。

実行:
  python migrations/2026-09-04_nfc_normalize.py
  python migrations/2026-09-04_nfc_normalize.py --commit
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import unicodedata
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
FIELDS = ("name", "name_jp", "set_name_official")


def run(commit: bool) -> None:
    db = sqlite3.connect(Path(api._DB_PATH))
    db.row_factory = sqlite3.Row
    rows = db.execute("SELECT id, category, product_id, name, name_jp, set_name_official "
                      "FROM products").fetchall()
    hit, done = Counter(), 0
    print(f"=== NFC 正規化 ({'APPLY' if commit else 'DRY-RUN'}) ===")
    for r in rows:
        upd = {}
        for f in FIELDS:
            v = r[f]
            if v and unicodedata.normalize("NFC", v) != v:
                upd[f] = unicodedata.normalize("NFC", v)
                hit[(r["category"], f)] += 1
        if not upd:
            continue
        if commit:
            sets = ", ".join(f"{k}=?" for k in upd)
            db.execute(f"UPDATE products SET {sets}, updated_at=? WHERE id=?",
                       (*upd.values(), NOW, r["id"]))
            done += 1
            if done % 200 == 0:          # 途中保存
                db.commit()
                print(f"    ... {done}行 保存")
    if commit:
        db.commit()
    db.close()
    for k, n in hit.most_common():
        print(f"  {k[0]:16s} {k[1]:20s} {n}箇所")
    print("")
    print(f"{'適用' if commit else '(dry-run — --commit で適用)'} {sum(hit.values())}箇所")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--commit", action="store_true")
    run(p.parse_args().commit)
