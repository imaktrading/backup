# -*- coding: utf-8 -*-
"""トレーナー (人物) の英語名を Bulbapedia との突き合わせで直す (2026-09-11).

HQ 依頼 `requests/2026-09-09_trainer_name_en_3way_wrong.md` Q2/Q3。
`tools/verify_trainer_names.py` の結果 (`trainer_name_check.json`) のうち、**人物名だけ**を扱う。

## FIX — 正しい英語名が確定したもの

Bulbapedia で「日本語名で検索 → 候補ページの jname が日本語名と完全一致」した英語名に差し替える。
**今の値が下の「誤り」と一致する行だけ**を書き換える (正しい値の行は触らない)。

## CLEAR — 誤りは確実だが、正しい英語名が確定しないもの

今の英語名のページの jname が別人 (例 Klara = クララ、ラビ ではない)。推測で埋めず空欄にする
(出品は fail-closed で止まる。誤った名前で出すよりよい)。

グッズ・フォルム違い・カード名 (ウルトラボール / ポワルン 等) は **触らない**。
ゲームとカードで英語名が違うことがあり、Bulbapedia の人物ページでは判定できないため。

実行:
    python migrations/2026-09-11_pokemon_trainer_name_en_bulbapedia.py
    python migrations/2026-09-11_pokemon_trainer_name_en_bulbapedia.py --commit
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
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

# 日本語名: (今の誤った値, 正しい値)   ← Bulbapedia jname 完全一致で確定 (2026-09-11)
FIX = {
    "アカマツ": ("Piers", "Crispin"),     "アンズ": ("Karen", "Janine"),
    "ウカッツ": ("Wally", "Cara Liss"),   "オモダカ": ("Crispin", "Geeta"),
    "オリーヴ": ("Olive", "Oleana"),      "カエデ": ("Tulip", "Katy"),
    "クチナシ": ("Poppy", "Nanu"),        "ゲン": ("Bede", "Riley"),
    "コルサ": ("Gordie", "Brassius"),     "ゴジカ": ("Fantina", "Olympia"),
    "サザレ": ("Lacey", "Perrin"),        "トロバ": ("Tierno", "Trevor"),
    "ドラセナ": ("Drayton", "Drasna"),    "ピオニー": ("Peonia", "Peony"),
    "ホミカ": ("Nessa", "Roxie"),         "マツリカ": ("Acerola", "Mina"),
    "ユカリ": ("Dawn", "Jacinthe"),       "リップ": ("Tyme", "Tulip"),
}
# 日本語名: 今の誤った値   ← 英語名のページの jname が別人。正解は未確定なので空欄に
CLEAR = {
    "ジュン": "Crystal", "リッシ": "Cynthia", "フトゥー": "Brassius", "ラビ": "Klara",
    "ベルのまごころ": "Skyla", "おじょうさま": "Lacey", "ミツバ": "Falkner", "ネルケ": "Melony",
}
SOURCE = "official_en_bulbapedia_jname_20260911"
CACHE = Path("C:/dev/iMak_data/catalog/pokemon_translation_cache/ja_en_api_translated.json")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    a = ap.parse_args()
    db = sqlite3.connect(str(api._DB_PATH), timeout=120)
    db.row_factory = sqlite3.Row
    now = datetime.now().isoformat(timespec="seconds")
    stat, todo = Counter(), []
    names = list(FIX) + list(CLEAR)
    q = ",".join("?" * len(names))
    for r in db.execute(f"SELECT id, product_id, name_jp, name_en, specs FROM products "
                        f"WHERE category='pokemon_tcg' AND name_jp IN ({q})", names):
        jp, cur = r["name_jp"], r["name_en"] or ""
        if jp in FIX and cur == FIX[jp][0]:
            new, src = FIX[jp][1], SOURCE
        elif jp in CLEAR and cur == CLEAR[jp]:
            new, src = "", "cleared_wrong_bulbapedia_20260911"
        else:
            stat["今の値が誤りの一覧と違う (触らない)"] += 1
            continue
        stat["差し替え" if new else "空欄に"] += 1
        todo.append((r, new, src))
    print(f"=== トレーナー名 ({'APPLY' if a.commit else 'DRY-RUN'}) ===")
    for r, new, _ in todo:
        print(f"    {r['product_id']:12s} {r['name_jp']:8s} {r['name_en']} -> {new or '(空欄)'}")
    for k, v in stat.most_common():
        print(f"  {k:30s} {v}")
    if a.commit:
        for r, new, src in todo:
            s = json.loads(r["specs"] or "{}")
            if s.get("character_name") == r["name_en"]:
                s["character_name"] = new
            db.execute("UPDATE products SET name_en=?, name_en_source=?, specs=?, updated_at=? "
                       "WHERE id=?", (new, src, json.dumps(s, ensure_ascii=False), now, r["id"]))
        db.commit()
        cache = json.loads(CACHE.read_text(encoding="utf-8"))
        for jp, (_, en) in FIX.items():
            if jp in cache:
                cache[jp] = en
        for jp in CLEAR:
            cache.pop(jp, None)
        CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    db.close()
    print(f"\n{'適用' if a.commit else '(dry-run — --commit で適用)'} {len(todo)}行")


if __name__ == "__main__":
    main()
