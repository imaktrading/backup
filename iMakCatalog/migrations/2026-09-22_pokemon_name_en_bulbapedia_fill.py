# -*- coding: utf-8 -*-
"""ポケモンの英語名: キハダの取り違え是正 + 空欄の補充 (2026-09-22).

判定 (1丁目1番地): **①カタログのデータが誤り/不足**。
依頼: requests/2026-09-21_kihada_name_en_katy.md / 2026-09-21_pokemon_name_en_blank_bel.md

根拠は 2026-09-22 に Bulbapedia (API action=parse) を取り直した値:
- `Dendra` の jname=キハダ / `Katy` の jname=カエデ → キハダ5行の Katy は取り違え
- 空欄の各カード名は、カードページの `(Japanese: '''<名前>''')` と日本語版の番号が一致し、
  かつ **英語版の収録番号が実在する** (000/000 の仮置きでない) ものだけ入れる

入れない (英語版が未発売 = 英語名が存在しない):
  ストームエメラルダ (M6) のうち伝説の山頂以外 / デウロ (M-P-143) / サチコEX (XYP-298)

実行: python migrations/2026-09-22_pokemon_name_en_bulbapedia_fill.py [--commit]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

DB = "C:/dev/iMak_data/catalog/products.sqlite"
SRC = "official_en_bulbapedia_jname_20260922"

# name_jp -> name_en (空欄の行、または Katy 取り違えの行にだけ当てる)
FILL = {
    "キハダ": "Dendra",
    "ベルのまごころ": "Bianca's Devotion",
    "ネルケ": "Clive",
    "ジュン": "Barry",
    "おじょうさま": "Lady",
    "ミツバ": "Honey",
    "超ブーストエネルギー": "Super Boost Energy",
    "あなあけスコップ": "Hole-Digging Shovel",
    "瘴気の谷": "Miasma Valley",
    "伝説の山頂": "Legendary Summit",
    # アビスアイ (M5) = 英語版 Pitch Black
    "ダークベル": "Dark Bell",
    "ごうかいボム": "Tremendous Bomb",
    "リトライバッジ": "Backtrack Badge",
    "カスミの元気": "Misty's Vitality",
    "グラジオの決戦": "Gladion's Final Battle",
    "サビ組のしたっぱ": "Rust Syndicate Grunt",
    "ムク": "Gwynn",
    "化石採掘場": "Fossil Quarry",
    "ボルト雷エネルギー": "Voltaic L Energy",
    "シャドー悪エネルギー": "Shadowy D Energy",
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    a = ap.parse_args()
    c = sqlite3.connect(DB, timeout=120)
    now = datetime.now().isoformat(timespec="seconds")
    n = 0
    for jp, en in FILL.items():
        rows = c.execute(
            "select product_id, coalesce(name_en,'') from products where category='pokemon_tcg' "
            "and name_jp=? and (coalesce(name_en,'')='' or (name_jp='キハダ' and name_en='Katy'))",
            (jp,)).fetchall()
        for pid, old in rows:
            print(f"{pid:12} {jp:12} {old!r:8} -> {en}")
            n += 1
            if a.commit:
                c.execute("update products set name_en=?, name_en_source=?, updated_at=? "
                          "where category='pokemon_tcg' and product_id=?", (en, SRC, now, pid))
    # character_name (eBay C:Character の元) も英語に揃える。同種の既存行
    # (Boss's Orders / Rare Candy 等) は character_name = name_en の形
    m = 0
    for pid, en, sp in c.execute(
            "select product_id, name_en, specs from products where category='pokemon_tcg' and name_en_source=?",
            (SRC,)).fetchall():
        d = json.loads(sp or "{}")
        cn = d.get("character_name") or ""
        if cn == en:
            continue
        if cn and cn.isascii() and cn != "Katy":
            continue
        d["character_name"] = en
        d["character_name_source"] = "name_en_20260922"
        m += 1
        if a.commit:
            c.execute("update products set specs=?, updated_at=? where category='pokemon_tcg' and product_id=?",
                      (json.dumps(d, ensure_ascii=False), now, pid))
    if a.commit:
        c.commit()
    print(f"{'更新' if a.commit else 'dry-run'} name_en {n}行 / character_name {m}行")


if __name__ == "__main__":
    main()
