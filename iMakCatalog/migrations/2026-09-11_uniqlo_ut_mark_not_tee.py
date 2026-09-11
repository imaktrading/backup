# -*- coding: utf-8 -*-
"""UT ではない物 (手袋・ストール・アートブック等) を uniqlo_ut から外す (2026-09-11).

## なぜ要るか

`uniqlo_ut_discover.py` は UT かどうかを **category == "ut graphic tees"** だけで見ていた。
ところが公式は、無地の手袋・ストール・ネックウォーマー・アートブックまで
その category に置いている (subcategory "others" / class "accessories")。

実測 (2026-09-11): 探索で拾った 602件のうち **194件がこれ**。

    E409202-000  ファンクショングローブ          accessories / others
    E418377-000  ライトストール                  accessories / others
    E475752-000  カウズ + ウォーホル アートブック  accessories / others

エアリズムの肌着 (innerwear) や パフテックベスト (outerwear) も数件入っていた。

## 何をするか

保管してある公式 detail の生 JSON (`_raw/uniqlo_ut/detail_<pid>.json.gz`) を読み、
**class が tops でない大人の行**を消す。値は公式の分類のまま、推測しない。

- 生 JSON が無い行は触らない (判定の根拠が無い)
- キッズ・ベビーは元から対象外 (作業しないだけで行は残している) なので触らない

★scraper 側も直してある (`UT_CLASS = "tops"`)。次からは入らない。
★消した品番は探索の state に「叩き済み」として残っているので、再実行で戻ってこない。

実行:
    python migrations/2026-09-11_uniqlo_ut_drop_non_tops.py
    python migrations/2026-09-11_uniqlo_ut_drop_non_tops.py --commit
"""
from __future__ import annotations

import argparse
import gzip
import json
import shutil
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

RAW = Path("C:/dev/iMak_data/catalog/_raw/uniqlo_ut")
KID = {"KIDS", "BABY"}


def official_class(pid: str) -> str | None:
    p = RAW / f"detail_{pid}.json.gz"
    if not p.exists():
        return None
    r = json.loads(gzip.open(p, "rt", encoding="utf-8").read())
    r = r.get("result", r)
    return ((r.get("breadcrumbs") or {}).get("class") or {}).get("name") or ""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    a = ap.parse_args()

    db = sqlite3.connect(str(api._DB_PATH), timeout=120)
    db.row_factory = sqlite3.Row
    stat, drop = Counter(), []
    for r in db.execute("SELECT id, product_id, name, specs FROM products "
                        "WHERE category='uniqlo_ut'"):
        if str(json.loads(r["specs"] or "{}").get("gender") or "").upper() in KID:
            stat["キッズ・ベビー (触らない)"] += 1
            continue
        cls = official_class(r["product_id"])
        if cls is None:
            stat["生 JSON 無し (触らない)"] += 1
        elif cls == "tops":
            stat["tops (残す)"] += 1
        else:
            stat[f"{cls} (外す)"] += 1
            drop.append(r)

    print(f"=== UT ではない物を外す ({'APPLY' if a.commit else 'DRY-RUN'}) ===")
    for k, v in stat.most_common():
        print(f"  {k:28s} {v}")
    for r in drop[:15]:
        print(f"    - {r['product_id']}  {r['name']}")
    if len(drop) > 15:
        print(f"    … ほか {len(drop) - 15}件")

    if a.commit and drop:
        db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        bak = api._DB_PATH.with_name(
            f"products.sqlite.pre_ut_drop_non_tops_{datetime.now():%Y%m%d_%H%M%S}")
        shutil.copy2(api._DB_PATH, bak)
        print(f"  backup: {bak.name}")
        db.executemany("DELETE FROM products WHERE id=?", [(r["id"],) for r in drop])
        db.commit()
    db.close()
    print(f"\n{'適用' if a.commit else '(dry-run — --commit で適用)'} {len(drop)}行")


if __name__ == "__main__":
    main()
