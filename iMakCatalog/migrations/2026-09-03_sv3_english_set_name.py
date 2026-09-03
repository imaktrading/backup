"""SV3 の 141行に **英語版セット名** が焼かれていたのを直す (2026-09-03).

依頼: `requests/2026-09-02_sv3_english_set_name.md` (窓口 → カタログ)
判定: **①カタログのデータが誤り** → catalog 側で直す。

    拡張パック「黒炎の支配者」  stored='SV03: Obsidian Flames'  (英語版 SV3 の名前)
                              -> 'Sv3: Ruler of the Black Flame'  (eBay master に在る日本語版の値)

8/23 の確定 (英語版セット名は使わない) で 1,729行を直した時に **ここだけ残った**。
理由: 0埋めの US 式コード `SV03:` が頭に付いていて、弾コード照合 (§0) が `SV3` と
結び付けられなかったため。§0b も素通りする (eBay master に実在する値なので)。

restamp では直らない (格下げ禁止の守り: stored が master の値だと上書きしない) ので個別に直す。

実行:
  python migrations/2026-09-03_sv3_english_set_name.py
  python migrations/2026-09-03_sv3_english_set_name.py --commit
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
SET_OFFICIAL = "拡張パック「黒炎の支配者」"
WRONG = "SV03: Obsidian Flames"
RIGHT = "Sv3: Ruler of the Black Flame"


def run(commit: bool) -> None:
    db = sqlite3.connect(Path(api._DB_PATH))
    db.row_factory = sqlite3.Row
    rows = db.execute(
        "SELECT id, product_id, specs FROM products WHERE category='pokemon_tcg' "
        "AND set_name_official=? AND json_extract(specs,'$.set_name_ebay')=?",
        (SET_OFFICIAL, WRONG)).fetchall()
    print(f"=== SV3 ({'APPLY' if commit else 'DRY-RUN'}) — {len(rows)}行 ===")
    print(f"  {WRONG!r} -> {RIGHT!r}")
    print(f"  例: {', '.join(r['product_id'] for r in rows[:5])}")
    if commit:
        for r in rows:
            s = json.loads(r["specs"] or "{}")
            s["set_name_ebay"] = RIGHT
            s["set_name_ebay_source"] = "sv3_english_set_fix_20260903"
            db.execute("UPDATE products SET specs=?, updated_at=? WHERE id=?",
                       (json.dumps(s, ensure_ascii=False), NOW, r["id"]))
        db.commit()
    db.close()
    print("")
    print(f"{'適用' if commit else '(dry-run — --commit で適用)'} {len(rows)} 行")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--commit", action="store_true")
    run(p.parse_args().commit)
