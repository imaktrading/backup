# -*- coding: utf-8 -*-
"""機械翻訳のまま誤っていたトレーナー名 5組を直す (2026-09-13).

HQ 依頼 `requests/2026-09-11_pokemon_trainer_name_en_chili_rika.md` Q2 /
`requests/2026-09-12_pokemon_mikuri_name_en_wallace.md` Q4:
「衝突検査 (同じ英語名が2つの日本語名に付く) だけでは、ある日本語名の全行が同じ誤りの型は
永久に捕まらない」。そのとおりなので、点検の対象を
**機械翻訳 (`claude_api` / `rule_trainer_dict`) の人物名 367組 全部**に広げて Bulbapedia と突き合わせた
(`tools/verify_trainer_names.py` / 結果 `trainer_name_check_claude_api.json`)。

そこで新たに出た5組 (英語名のページの jname が日本語名と一致した物だけ採用):

    ゴヨウ   Palmer   -> Lucian     (Palmer は クロツグ)
    ザクロ   Wikstrom -> Grant      (Wikstrom は ガンピ)
    マチエール Valerie  -> Emma       (Valerie は マーシュ)
    ガイ     Guy      -> Urbain
    セイジ   Sage     -> Salvatore

実行:
    python migrations/2026-09-13_pokemon_trainer_name_en_claude_api_5.py
    python migrations/2026-09-13_pokemon_trainer_name_en_claude_api_5.py --commit
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

FIX = {"ゴヨウ": ("Palmer", "Lucian"), "ザクロ": ("Wikstrom", "Grant"),
       "マチエール": ("Valerie", "Emma"), "ガイ": ("Guy", "Urbain"),
       "セイジ": ("Sage", "Salvatore")}
SOURCE = "official_en_bulbapedia_jname_20260913"
CACHE = Path("C:/dev/iMak_data/catalog/pokemon_translation_cache/ja_en_api_translated.json")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    a = ap.parse_args()
    db = sqlite3.connect(str(api._DB_PATH), timeout=120)
    db.row_factory = sqlite3.Row
    now = datetime.now().isoformat(timespec="seconds")
    print(f"=== 機械翻訳のトレーナー名 5組 ({'APPLY' if a.commit else 'DRY-RUN'}) ===")
    n = 0
    for jp, (bad, good) in FIX.items():
        for r in db.execute("SELECT id, product_id, name_en, specs FROM products "
                            "WHERE category='pokemon_tcg' AND name_jp=? AND name_en=?", (jp, bad)):
            s = json.loads(r["specs"] or "{}")
            if s.get("character_name") == bad:
                s["character_name"] = good
            print(f"    {r['product_id']:10s} {jp:6s} {bad} -> {good}")
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
