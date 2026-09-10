# -*- coding: utf-8 -*-
"""起こした廃盤 UT に **性別** を入れる (2026-09-10).

## なぜ要るか

`uniqlo_ut_revive.py` が 126件を起こしたが、**性別を入れていなかった**。
キッズは対象外 (2026-09-09 ユーザー確定「キッズはいらない」) なのに、性別が空だと
「大人」として扱われ、実寸表の Selenium が 1件15秒かけて叩きに行く。

実測 (2026-09-10): 実寸表が取れなかった11件を1件ずつ開いたら、**全部キッズ**だった。
モーダルは開いていて表も在る。ただ **サイズが `100(3-4歳)` 〜 `160(14歳)`** なので、
大人のサイズ名 (XS/S/M/L…) を探す読み方に当たらず「表が開かなかった」に落ちていた。

    E447282-000  ピクサー コレクション UT
    E475703-000  絵本コレクション UT/うさこちゃんとどうぶつえん
    E474737-000  GIRLS サンリオキャラクターズ クロップドUT     ← 名前は GIRLS だが公式は KIDS

## 何をするか

`revived_at` の在る行を公式 detail API で引き直し、`genderName` を `specs.gender` /
`specs.department` に入れる (現行の取り込みと同じ形)。値は**公式のまま**、推測しない。

★scraper 側も直してある (`uniqlo_ut_revive.py`)。次からは起こす時点で入る。

実行:
    python migrations/2026-09-10_ut_revived_gender_backfill.py
    python migrations/2026-09-10_ut_revived_gender_backfill.py --commit
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
import api  # noqa: E402
sys.path.insert(0, str(_ROOT / "scrapers"))
import uniqlo_ut as U  # noqa: E402
import uniqlo_ut_enrich as E  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    a = ap.parse_args()

    db = sqlite3.connect(str(api._DB_PATH), timeout=120)
    db.row_factory = sqlite3.Row
    rows = [r for r in db.execute(
        "SELECT id, product_id, name, specs FROM products WHERE category='uniqlo_ut'")
        if json.loads(r["specs"] or "{}").get("revived_at")]
    todo = [r for r in rows if not json.loads(r["specs"] or "{}").get("gender")]
    print(f"  起こした行 {len(rows)}件 / 性別が入っている {len(rows) - len(todo)}件 は飛ばす")
    print(f"=== 性別の埋め ({'APPLY' if a.commit else 'DRY-RUN'}) — 対象 {len(todo)}件 ===")

    now = datetime.now().isoformat(timespec="seconds")
    stat, n = Counter(), 0
    for r in todo:
        try:
            d = E.fetch(r["product_id"]) or {}
        except Exception as e:
            stat[f"引けない ({type(e).__name__})"] += 1
            time.sleep(1.0)
            continue
        g = (d.get("genderName") or "").strip()
        if not g:
            stat["公式に性別が無い"] += 1
            time.sleep(1.0)
            continue
        stat[g] += 1
        if a.commit:
            s = json.loads(r["specs"] or "{}")
            s["gender"] = g
            s["department"] = U._gender_to_dept(g)
            db.execute("UPDATE products SET specs=?, updated_at=? WHERE id=?",
                       (json.dumps(s, ensure_ascii=False), now, r["id"]))
            db.commit()                      # ★1件ごとに保存
            n += 1
        time.sleep(1.0)
    db.close()
    print("")
    for k, v in stat.most_common():
        print(f"  {k:24s} {v}")
    print("")
    print(f"{'適用' if a.commit else '(dry-run — --commit で適用)'} {n}行")


if __name__ == "__main__":
    main()
