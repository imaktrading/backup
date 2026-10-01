# -*- coding: utf-8 -*-
"""弾の無い基本エネルギー 1行 (`cardID-36256`) を消す (2026-10-02).

依頼: `requests/2026-10-02_pokemon_basic_energy_row_delete_go.md` [IMPLEMENT-GO]
ユーザー許可: 2026-10-02「じゃ、そうしよう」/「消した方がいいなら、消して」

## 判定: ① カタログに在るべきでない行

CLAUDE.md「番号が無いカード (基本エネルギー等) は登録しない」より前に入った行。

2026-10-02 に公式を取り直して確かめた:

    https://www.pokemon-card.com/card-search/details.php/card/36256/regu/all
      -> ページは在るが **収録弾の記載が無い** (名前と「基本エネルギー」だけ)
      -> 絵も /ENE/ (エネルギーの一覧) で、弾のフォルダに無い

つまり **公式も弾を持っていない** = `set_name_official` は埋める手が無い。
他の基本エネルギー 665行は弾を持っている (例 `cardID-49464` = スタートデッキ100
バトルコレクション) ので、弾の無いのはこの1行だけ。

これが残っていると仕上げ (`finish_ingest.py`) が毎月 `set=None` で赤を出し続ける。

## 使っている出品

0件 (HQ 確認。基本エネルギーの出品は `SV2D-099` 基本くさエネルギー UR の1件だけで別の行)。

## 控え

消す前に行の中身を JSON で残す (`_backups/..._deleted_rows.json`)。戻す時はこれを入れ直す。

実行: python migrations/2026-10-02_delete_setless_basic_energy_row.py [--commit]
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

DB = "C:/dev/iMak_data/catalog/products.sqlite"
BK = Path("C:/dev/iMak_data/catalog/_backups")
PID = "cardID-36256"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def main() -> None:
    commit = "--commit" in sys.argv
    c = sqlite3.connect(DB, timeout=180)
    c.row_factory = sqlite3.Row
    rows = c.execute("SELECT * FROM products WHERE product_id=?", (PID,)).fetchall()
    print(f"=== 弾の無い基本エネルギーを消す ({'APPLY' if commit else 'DRY-RUN'}) ===")
    for r in rows:
        print(f"  id={r['id']} {r['product_id']} | {r['name']} | "
              f"set={r['set_name_official']} | {r['source']}")
    if len(rows) != 1:
        print(f"⚠️ 1行のはずが {len(rows)}行 → 何もしない")
        return
    if not commit:
        print("\n(dry-run — --commit で適用)")
        return

    BK.mkdir(parents=True, exist_ok=True)
    out = BK / f"{datetime.now():%Y%m%d_%H%M}_deleted_rows.json"
    out.write_text(json.dumps([dict(r) for r in rows], ensure_ascii=False, indent=1),
                   encoding="utf-8")
    print(f"\n控え: {out.name}")
    c.execute("DELETE FROM products WHERE product_id=?", (PID,))
    c.commit()
    left = c.execute("SELECT count(*) FROM products WHERE product_id=?", (PID,)).fetchone()[0]
    setless = c.execute("SELECT count(*) FROM products WHERE category='pokemon_tcg' "
                        "AND set_name_official IS NULL AND "
                        "json_extract(specs,'$.set_name_ebay') IS NULL").fetchone()[0]
    c.close()
    print(f"消した。残り {left}行 / 弾も eBay 値も無いポケモンの行 {setless}行")


if __name__ == "__main__":
    main()
