# -*- coding: utf-8 -*-
"""ミクリ / チリ の英語名を直す (2026-09-13).

HQ 依頼 `requests/2026-09-12_pokemon_mikuri_name_en_wallace.md` (緊急度 高。入稿CSVに1行載った) と
`requests/2026-09-11_pokemon_trainer_name_en_chili_rika.md`。どちらも `name_en_source='claude_api'`。

Bulbapedia を 2026-09-13 に再取得して確認:
    Wallace = ミクリ   (Juan は アダン)
    Rika    = チリ     (Chili は ポッド)

直す場所: products の `name_en` / `name_en_source` / `specs.character_name` と、
翻訳キャッシュ `pokemon_translation_cache/ja_en_api_translated.json` (直さないと次の取り込みで戻る)。

実行:
    python migrations/2026-09-13_pokemon_mikuri_chiri_name_en.py
    python migrations/2026-09-13_pokemon_mikuri_chiri_name_en.py --commit
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
import api  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

FIX = {"ミクリ": ("Juan", "Wallace"), "チリ": ("Chili", "Rika")}
SOURCE = "official_en_bulbapedia_jname_20260913"
CACHE = Path("C:/dev/iMak_data/catalog/pokemon_translation_cache/ja_en_api_translated.json")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    a = ap.parse_args()
    db = sqlite3.connect(str(api._DB_PATH), timeout=120)
    db.row_factory = sqlite3.Row
    now = datetime.now().isoformat(timespec="seconds")
    print(f"=== ミクリ / チリ の英語名 ({'APPLY' if a.commit else 'DRY-RUN'}) ===")
    n = 0
    for jp, (bad, good) in FIX.items():
        for r in db.execute("SELECT id, product_id, name_en, specs FROM products "
                            "WHERE category='pokemon_tcg' AND name_jp=?", (jp,)):
            if (r["name_en"] or "") != bad:
                print(f"    {r['product_id']:10s} {jp} は {r['name_en']} (誤りの値と違うので触らない)")
                continue
            s = json.loads(r["specs"] or "{}")
            if s.get("character_name") == bad:
                s["character_name"] = good
            print(f"    {r['product_id']:10s} {jp:5s} {bad} -> {good}")
            n += 1
            if a.commit:
                db.execute("UPDATE products SET name_en=?, name_en_source=?, specs=?, updated_at=? "
                           "WHERE id=?", (good, SOURCE, json.dumps(s, ensure_ascii=False),
                                          now, r["id"]))
    if a.commit:
        db.commit()
        cache = json.loads(CACHE.read_text(encoding="utf-8"))
        for jp, (bad, good) in FIX.items():
            if cache.get(jp) == bad:
                cache[jp] = good
                print(f"    キャッシュ {jp}: {bad} -> {good}")
        CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    db.close()
    print(f"\n{'適用' if a.commit else '(dry-run — --commit で適用)'} {n}行")


if __name__ == "__main__":
    main()
