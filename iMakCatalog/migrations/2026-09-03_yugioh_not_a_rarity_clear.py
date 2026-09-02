"""レアリティでない値が C:Rarity に出る 117行を空欄にする (2026-09-03).

判定 (1丁目1番地): **①カタログのデータが誤り** → catalog 側で直す。

`specs.rarity_ebay` に `New` / `2` / `3` / `European debut` のような、そもそも
レアリティでない値が入っている (取り込み元の生値をそのまま通した分)。
出すと C:Rarity が「New」等になる = 誤記載。**空欄 (fail-closed) にする**。

## なぜ今まで残ったか

監査 §8 はこれを 2026-08-21 に見つけていた (当時 118行) が、**毎日の監査は
pokemon しか見ていなかった** ため、遊戯王の分は誰の画面にも出ていなかった。
2026-09-03 に検収 (`tools/claim_check.py`) を全カテゴリで走らせて再発見。

## やること

`rarity_ebay` を空にし、`rarity_ebay_status='not_a_rarity_cleared_20260903'` を残す
(消した理由が後から分かるように。生値 `specs.rarity` は触らない)。

実行:
  python migrations/2026-09-03_yugioh_not_a_rarity_clear.py
  python migrations/2026-09-03_yugioh_not_a_rarity_clear.py --commit
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import api  # noqa: E402
import set_name_integrity_audit as A  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

NOW = datetime.now().isoformat(timespec="seconds")


def run(commit: bool) -> None:
    db = sqlite3.connect(Path(api._DB_PATH))
    db.row_factory = sqlite3.Row
    rows = db.execute(
        "SELECT id, category, product_id, specs FROM products "
        "WHERE IFNULL(json_extract(specs,'$.rarity_ebay'),'')<>''").fetchall()
    hit = Counter()
    ids = []
    for r in rows:
        s = json.loads(r["specs"] or "{}")
        v = str(s.get("rarity_ebay") or "")
        if A._looks_like_rarity(v):          # 監査 §8 と同じ判定を使う (二重定義しない)
            continue
        hit[(r["category"], v)] += 1
        ids.append((r["id"], s))
    print(f"=== レアリティでない値 ({'APPLY' if commit else 'DRY-RUN'}) — {len(ids)}行 ===")
    for (cat, v), n in hit.most_common(12):
        print(f"  {cat:14s} {v!r:28s} {n}行")
    if commit:
        for _id, s in ids:
            s["rarity_ebay"] = ""
            s["rarity_ebay_status"] = "not_a_rarity_cleared_20260903"
            db.execute("UPDATE products SET specs=?, updated_at=? WHERE id=?",
                       (json.dumps(s, ensure_ascii=False), NOW, _id))
        db.commit()
    db.close()
    print("")
    print(f"{'適用' if commit else '(dry-run — --commit で適用)'} {len(ids)} 行")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--commit", action="store_true")
    run(p.parse_args().commit)
