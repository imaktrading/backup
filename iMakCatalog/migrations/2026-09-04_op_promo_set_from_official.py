"""プロモの `set_name_official` を **公式の収録商品名**に直す (2026-09-04).

判定: **①カタログのデータが誤り** → catalog 側で直す。

## 何が誤りか

scraper が読む bandai-tcg-plus の `card_set` は、プロモだと **まとめ名**しか返さない
(`限定商品収録カード` / `プロモーションカード` / `Promotion Card` / `Other Product Card`)。
どの商品に入っていたカードかが catalog に残らないので、

  - eBay の Set が商品ではなく まとめ名になる
  - 3rd ANNIVERSARY SET のように「引き当てられない」プロモが出る
  - **新しいプロモが出るたびに同じ問題が再発する** (今回の悪循環の根)

公式カードリストの弾ページには 1枚ごとの収録商品名 (`getInfo`) が載っているので、そこから直す。

## 安全のため、直すのは次を満たす行だけ

  1. 今の `set_name_official` が **まとめ名**である (商品名が入っている行は触らない)
  2. その券面番号が、公式ページに **1商品しか無い** (複数なら人が見るまで触らない = fail-closed)

実行:
  python migrations/2026-09-04_op_promo_set_from_official.py [--commit]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import api  # noqa: E402
import official_drift_check as D  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

NOW = datetime.now().isoformat(timespec="seconds")
CAT = "one_piece_tcg"
BUCKETS = {"限定商品収録カード", "プロモーションカード", "Promotion Card",
           "Other Product Card", "Promotion Cards"}
SERIES = ("550801", "550901")     # 限定商品収録カード / プロモーションカード


def run(commit: bool) -> None:
    official = defaultdict(set)
    for sid in SERIES:
        for c in D.parse_cards(D._get(D.LIST_URL.format(sid=sid))):
            if c["get_info"]:
                official[c["no"]].add(c["get_info"])

    db = sqlite3.connect(Path(api._DB_PATH))
    db.row_factory = sqlite3.Row
    rows = db.execute(
        "SELECT id, product_id, set_name_official, specs FROM products WHERE category=?",
        (CAT,)).fetchall()
    upd, ambiguous = [], Counter()
    for r in rows:
        cur = (r["set_name_official"] or "").strip()
        if cur not in BUCKETS:
            continue
        no = (r["product_id"] or "").split("_")[0]
        cands = official.get(no) or set()
        if len(cands) == 1:
            upd.append((r["id"], r["product_id"], cur, next(iter(cands))))
        elif len(cands) > 1:
            ambiguous[no] = len(cands)

    print(f"=== プロモの収録商品名を公式から入れる ({'APPLY' if commit else 'DRY-RUN'}) ===")
    print(f"  直せる {len(upd)}行 / 商品が複数で触らない {len(ambiguous)}番号")
    for _, pid, cur, new in upd[:8]:
        print(f"    {pid:20s} {cur!r} -> {new[:38]!r}")
    if commit:
        done = 0
        for _id, _pid, _cur, new in upd:
            db.execute("UPDATE products SET set_name_official=?, set_name=?, updated_at=? "
                       "WHERE id=?", (new, new, NOW, _id))
            done += 1
            if done % 200 == 0:        # 途中保存
                db.commit()
                print(f"    ... {done}行 保存")
        db.commit()
    db.close()
    print("")
    print(f"{'適用' if commit else '(dry-run — --commit で適用)'} {len(upd)} 行")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--commit", action="store_true")
    run(p.parse_args().commit)
