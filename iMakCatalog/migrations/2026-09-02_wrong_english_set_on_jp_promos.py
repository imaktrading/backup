"""雑誌付録・映画配布のプロモに **英語版の拡張パック名**が付いていたのを直す (2026-09-02).

判定 (1丁目1番地): **①カタログのデータが誤り** → catalog 側で直す。

## 何が誤りか

規約③「英語版の別セット名を使うのは禁止」(CLAUDE.md「eBay "Set" 欄に何を入れるか」)。
下の2セットは日本の雑誌付録 / 映画配布のプロモなのに、英語版の拡張パック名が入っていた。
バイヤーには「その英語版セットに収録されたカード」に見えるので、誤記載になる。

    小学館『月刊コロコロコミック』2006年12月号付録  <- 'Stormfront'  (英語版 2008年の拡張)
    映画公開記念ランダムパック2009                  <- 'Platinum'    (英語版 2009年の拡張)

`tools/restamp_set_name_ebay.py` は **格下げ禁止**の守りがあり、stored が eBay master の
値だと上書きしない (line 145)。今回はその守りが誤りを保存する側に働くので、個別に直す。
空欄だった行 (174 / 8) は 9/2 の変換表追加で既に新しい値が入っている。

## 直したあとの値 (規約②: 日本語セット名の英語表記)

    CoroCoro Comic December 2006
    2009 Movie Release Random Pack

実行:
  python migrations/2026-09-02_wrong_english_set_on_jp_promos.py
  python migrations/2026-09-02_wrong_english_set_on_jp_promos.py --commit
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
# (set_name_official, 誤って入っていた値, 正しい値)
TARGETS = [
    ("小学館『月刊コロコロコミック』2006年12月号付録", "Stormfront", "CoroCoro Comic December 2006"),
    ("映画公開記念ランダムパック2009", "Platinum", "2009 Movie Release Random Pack"),
]


def run(commit: bool) -> None:
    db = sqlite3.connect(Path(api._DB_PATH))
    db.row_factory = sqlite3.Row
    print(f"=== 英語版セット名の誤り是正 ({'APPLY' if commit else 'DRY-RUN'}) ===")
    total = 0
    for so, wrong, right in TARGETS:
        rows = db.execute(
            "SELECT id, product_id, specs FROM products WHERE category='pokemon_tcg' "
            "AND set_name_official=? AND json_extract(specs,'$.set_name_ebay')=?",
            (so, wrong)).fetchall()
        print(f"  {so}\n    {wrong!r} -> {right!r} : {len(rows)}行")
        for r in rows:
            s = json.loads(r["specs"] or "{}")
            s["set_name_ebay"] = right
            s["set_name_ebay_source"] = "fix_wrong_english_set_20260902"
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
