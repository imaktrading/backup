# -*- coding: utf-8 -*-
"""UT ではない物 (手袋・ストール・アートブック・リラコ等) に印を付ける (2026-09-11).

## なぜ要るか

`uniqlo_ut_discover.py` は UT かどうかを **category == "ut graphic tees"** だけで見ていた。
ところが公式は、無地の手袋・ストール・ネックウォーマー・アートブックまで
その category に置いている (subcategory "others" / class "accessories")。

実測 (2026-09-11): 探索で拾った 602件のうち **194件がこれ**。

    E409202-000  ファンクショングローブ          accessories / others
    E418377-000  ライトストール                  accessories / others
    E475752-000  カウズ + ウォーホル アートブック  accessories / others

エアリズムの肌着 (innerwear) や パフテックベスト (outerwear) も数件、
class が tops のまま入っているリラコ / ステテコ (パンツ。実寸表の形も違う) が 18件。

## 何をするか — 消さずに印を付ける

`specs.not_tee` に理由を入れる。カタログHTML / 実寸表 / 在庫 はこの印の行を扱わない。
行は消さない (生 JSON もそのまま。印を外せば元に戻る)。

判定:
- 保管してある公式 detail の生 JSON の class が tops でない → `class=<値>`
- 商品名に リラコ / ステテコ → `パンツ (リラコ/ステテコ)`
- 生 JSON が無い行は class を判定しない (根拠が無い)
- キッズ・ベビーは元から対象外なので触らない

★scraper 側も直してある (`UT_CLASS = "tops"`)。次からは入らない。

実行:
    python migrations/2026-09-11_uniqlo_ut_mark_not_tee.py
    python migrations/2026-09-11_uniqlo_ut_mark_not_tee.py --commit
"""
from __future__ import annotations

import argparse
import gzip
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

RAW = Path("C:/dev/iMak_data/catalog/_raw/uniqlo_ut")
KID = {"KIDS", "BABY"}
PANTS = ("リラコ", "ステテコ")


def official_class(pid: str) -> str | None:
    p = RAW / f"detail_{pid}.json.gz"
    if not p.exists():
        return None
    r = json.loads(gzip.open(p, "rt", encoding="utf-8").read())
    r = r.get("result", r)
    return ((r.get("breadcrumbs") or {}).get("class") or {}).get("name") or ""


def reason(pid: str, name: str) -> str | None:
    cls = official_class(pid)
    if cls not in (None, "tops"):
        return f"class={cls}"
    if any(w in (name or "") for w in PANTS):
        return "パンツ (リラコ/ステテコ)"
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    a = ap.parse_args()

    db = sqlite3.connect(str(api._DB_PATH), timeout=120)
    db.row_factory = sqlite3.Row
    now = datetime.now().isoformat(timespec="seconds")
    stat, todo = Counter(), []
    for r in db.execute("SELECT id, product_id, name, specs FROM products "
                        "WHERE category='uniqlo_ut'"):
        s = json.loads(r["specs"] or "{}")
        if str(s.get("gender") or "").upper() in KID:
            continue
        if s.get("not_tee"):
            stat["印あり (飛ばす)"] += 1
            continue
        why = reason(r["product_id"], r["name"])
        if why:
            stat[why] += 1
            todo.append((r, s, why))

    print(f"=== UT でない物に印 ({'APPLY' if a.commit else 'DRY-RUN'}) ===")
    for k, v in stat.most_common():
        print(f"  {k:28s} {v}")
    for r, _, why in todo[:10]:
        print(f"    - {r['product_id']}  {why:12s} {r['name']}")
    if a.commit:
        for r, s, why in todo:
            s["not_tee"] = why
            s["not_tee_at"] = now
            db.execute("UPDATE products SET specs=?, updated_at=? WHERE id=?",
                       (json.dumps(s, ensure_ascii=False), now, r["id"]))
        db.commit()
    db.close()
    print(f"\n{'適用' if a.commit else '(dry-run — --commit で適用)'} {len(todo)}行")


if __name__ == "__main__":
    main()
