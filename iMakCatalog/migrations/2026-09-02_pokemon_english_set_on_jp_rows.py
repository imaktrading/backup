"""日本語セットの行に **英語版セット名** が入っていた 22行を直す (2026-09-02).

判定 (1丁目1番地): **①カタログのデータが誤り** → catalog 側で直す。

## 何が誤りか

規約③「英語版の別セット名を使うのは禁止」。2026-08-23 に
「日本語版セットの eBay 値は在るので英語版名の例外は廃止」と確定済なのに、
下の行だけ残っていた。同じセットの他の行は正しい値なので、**1セットに2つの値**が
入っている状態 (§2 で見えていたが 0件維持の対象になっていなかった)。

    cardID-42944..  ハイクラスパック「VSTARユニバース」   'Crown Zenith'  ->  'S12a: Vstar Universe'   8行
    cardID-40091..  拡張パック「25th ANNIVERSARY…」      'Celebrations'  ->  'S8a: 25th Anniversary Collection' 8行
    SM-P-297/307    拡張パック「タッグボルト」             'Sun & Moon - Team Up' -> 'Sm-P: Sun & Moon Promos' 2行
    SM-P-360        拡張パック「ミラクルツイン」           'Unified Minds'        -> 同上 1行
    SM-P-006/007/010 拡張パック「コレクション サン」        'Sun & Moon'           -> 同上 3行

★`SM-P-*` は **プロモの刷り**なので、行き先は弾の名前ではなく promo の値にする
  (同じセットの他の SM-P 行は既に 'Sm-P: Sun & Moon Promos')。
★`cardID-*` は番号体系外の索引行。中身は日本語版のカードなので日本語版セットの値にする。

restamp は「格下げ禁止」(stored が eBay master の値なら上書きしない) の守りがあり、
'Crown Zenith' 等はまさに master の値なので触れない。よって個別 migration。

実行:
  python migrations/2026-09-02_pokemon_english_set_on_jp_rows.py
  python migrations/2026-09-02_pokemon_english_set_on_jp_rows.py --commit
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
PROMO = "Sm-P: Sun & Moon Promos"
# (set_name_official, 誤って入っていた値, 正しい値)
TARGETS = [
    ("ハイクラスパック 「VSTARユニバース」", "Crown Zenith", "S12a: Vstar Universe"),
    ("拡張パック「25th ANNIVERSARY COLLECTION」", "Celebrations", "S8a: 25th Anniversary Collection"),
    ("拡張パック「タッグボルト」", "Sun & Moon - Team Up", PROMO),
    ("拡張パック「ミラクルツイン」", "Unified Minds", PROMO),
    ("拡張パック「コレクション サン」", "Sun & Moon", PROMO),
]


def run(commit: bool) -> None:
    db = sqlite3.connect(Path(api._DB_PATH))
    db.row_factory = sqlite3.Row
    print(f"=== 英語版セット名の是正 ({'APPLY' if commit else 'DRY-RUN'}) ===")
    total = 0
    for so, wrong, right in TARGETS:
        rows = db.execute(
            "SELECT id, product_id, specs FROM products WHERE category='pokemon_tcg' "
            "AND set_name_official=? AND json_extract(specs,'$.set_name_ebay')=?",
            (so, wrong)).fetchall()
        print(f"  {so}\n    {wrong!r} -> {right!r} : {len(rows)}行 "
              f"({', '.join(r['product_id'] for r in rows[:3])}…)")
        for r in rows:
            s = json.loads(r["specs"] or "{}")
            s["set_name_ebay"] = right
            s["set_name_ebay_source"] = "fix_english_set_on_jp_rows_20260902"
            if commit:
                db.execute("UPDATE products SET specs=?, updated_at=? WHERE id=?",
                           (json.dumps(s, ensure_ascii=False), NOW, r["id"]))
        total += len(rows)
    if commit:
        db.commit()
    db.close()
    print("")
    print(f"{'適用' if commit else '(dry-run — --commit で適用)'} {total} 行")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--commit", action="store_true")
    run(p.parse_args().commit)
