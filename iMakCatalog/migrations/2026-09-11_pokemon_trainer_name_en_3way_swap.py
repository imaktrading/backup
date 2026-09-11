# -*- coding: utf-8 -*-
"""トレーナー3人の英語名の入れ替わりを直す (2026-09-11).

HQ 依頼 `requests/2026-09-09_trainer_name_en_3way_wrong.md`。判定 ①カタログのデータが誤り。

Bulbapedia を 2026-09-11 に再取得して確認 (HQ の 09-09 取得と一致):
    Penny   = ボタン     (カタログは Atticus)
    Giacomo = ピーニャ   (カタログは Penny)
    Atticus = シュウメイ (カタログは Ryme)

直す場所:
  1. products の 13行 — `name_en` / `name_en_source` / `specs.character_name`
  2. 元の表 `scrapers/pokemon_name_translation.py` の `"ボタン": "Atticus"` → Penny (コード側で修正)
  3. 翻訳キャッシュ `pokemon_translation_cache/ja_en_api_translated.json`
     `"ピーニャ": "Penny"` → Giacomo / `"シュウメイ": "Shumei"` → Atticus
     (シュウメイ は DB では Ryme、キャッシュでは Shumei と、どちらも誤っていた)

実行:
    python migrations/2026-09-11_pokemon_trainer_name_en_3way_swap.py
    python migrations/2026-09-11_pokemon_trainer_name_en_3way_swap.py --commit
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

FIX = {"ボタン": "Penny", "ピーニャ": "Giacomo", "シュウメイ": "Atticus"}
SOURCE = "official_en_bulbapedia_20260911"
CACHE = Path("C:/dev/iMak_data/catalog/pokemon_translation_cache/ja_en_api_translated.json")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    a = ap.parse_args()
    db = sqlite3.connect(str(api._DB_PATH), timeout=120)
    db.row_factory = sqlite3.Row
    now = datetime.now().isoformat(timespec="seconds")
    rows = db.execute(
        "SELECT id, product_id, name_jp, name_en, specs FROM products "
        "WHERE category='pokemon_tcg' AND name_jp IN (?,?,?) ORDER BY name_jp, product_id",
        tuple(FIX)).fetchall()
    print(f"=== トレーナー3人の英語名 ({'APPLY' if a.commit else 'DRY-RUN'}) — {len(rows)}行 ===")
    for r in rows:
        new = FIX[r["name_jp"]]
        s = json.loads(r["specs"] or "{}")
        print(f"    {r['product_id']:10s} {r['name_jp']:6s} {r['name_en']} -> {new}")
        s["character_name"] = new
        if a.commit:
            db.execute("UPDATE products SET name_en=?, name_en_source=?, specs=?, updated_at=? "
                       "WHERE id=?", (new, SOURCE, json.dumps(s, ensure_ascii=False), now, r["id"]))
    if a.commit:
        db.commit()
    db.close()

    cache = json.loads(CACHE.read_text(encoding="utf-8"))
    for jp, en in FIX.items():
        if jp in cache and cache[jp] != en:
            print(f"    cache {jp}: {cache[jp]} -> {en}")
            cache[jp] = en
    if a.commit:
        CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n{'適用' if a.commit else '(dry-run — --commit で適用)'}")


if __name__ == "__main__":
    main()
