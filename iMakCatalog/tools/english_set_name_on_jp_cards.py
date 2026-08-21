#!/usr/bin/env python3
"""日本版カードに英語版セット名が焼かれている行を洗い出す (書込前の一覧).

決定: requests/2026-08-21_set_rarity_final_plan_response_go.md 決定2
      「1,539行は今回の作業に含めて直す。ただし書き換える前に対象一覧を出すこと」

## 何が問題か
日本版「VSTARユニバース」のカードに `Crown Zenith` が焼かれている、のような行。
eBay には両方の綴りが在るので**絞り込みの都合では決まらない**。
現物が刷られた商品は日本版なので、`Crown Zenith` は**誤記載**にあたる。

## 判定
stored (specs.set_name_ebay) != derived (derive_set_name_ebay) で、
かつ stored が「英語版でしか出ていない商品名」の時だけ対象にする。
derived 側が空なら触らない (fail-closed)。

実行:
  python tools/english_set_name_on_jp_cards.py            # 一覧を出すだけ
  python tools/english_set_name_on_jp_cards.py --commit   # stored を derived に戻す
"""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import api  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

NOW = datetime.now().isoformat()
OUT_DIR = Path(r"C:\dev\iMak_data\catalog\requests")
OUT_CSV = OUT_DIR / "2026-08-21_english_set_name_on_jp_cards.csv"
OUT_MD = OUT_DIR / "2026-08-21_english_set_name_on_jp_cards.md"


def is_english_release_name(stored: str, derived: str) -> bool:
    """stored が『英語版でしか出ていない商品名』か.

    規則で当てない。derived (= 日本版セット名) と綴りが全く別物で、
    かつ stored 側が日本版の弾番号を含まないものを対象にする。
    弾番号つき ('S12a: Vstar Universe') は同じセットの別表記なので対象外。
    """
    if not stored or not derived:
        return False
    if stored == derived:
        return False
    a = "".join(ch for ch in stored.lower() if ch.isalnum())
    b = "".join(ch for ch in derived.lower() if ch.isalnum())
    if a == b or a in b or b in a:
        return False          # 表記ゆれ / 弾番号つき = 別問題
    return True


def collect(db):
    rows = []
    for r in db.execute("SELECT category, product_id, name, set_name_official, specs "
                        "FROM products WHERE set_name_official IS NOT NULL"):
        s = json.loads(r["specs"] or "{}")
        stored = s.get("set_name_ebay")
        derived = api.derive_set_name_ebay(r["category"], r["set_name_official"], r["product_id"])
        if not is_english_release_name(stored or "", derived or ""):
            continue
        rows.append(dict(category=r["category"], product_id=r["product_id"], name=r["name"],
                         set_name_official=r["set_name_official"],
                         stored=stored, derived=derived))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()

    db = sqlite3.connect(api._DB_PATH)
    db.row_factory = sqlite3.Row
    rows = collect(db)

    pairs = Counter((x["stored"], x["derived"]) for x in rows)
    print("=== 日本版カードに英語版セット名 (%s) ===" % ("APPLY" if args.commit else "REPORT"))
    print("対象 %d 行 / %d 組\n" % (len(rows), len(pairs)))
    print("%-42s %-38s %s" % ("焼いてある値 (誤)", "正しい値 (日本版)", "行数"))
    for (st, de), n in pairs.most_common():
        print("%-42s %-38s %d" % (st, de, n))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["category", "product_id", "name",
                                          "set_name_official", "stored", "derived"])
        w.writeheader()
        w.writerows(rows)
    with OUT_MD.open("w", encoding="utf-8") as f:
        f.write("# 日本版カードに英語版セット名が焼かれている行 (書込前の一覧)\n\n")
        f.write("生成: %s / 対象 **%d 行 / %d 組**\n\n" % (NOW, len(rows), len(pairs)))
        f.write("eBay には両方の綴りが在るため**絞り込みの都合では決まらない**。\n")
        f.write("現物が刷られた商品は日本版なので、英語版名は**誤記載**にあたる。\n\n")
        f.write("| 焼いてある値 (誤) | 正しい値 (日本版) | 行数 |\n|---|---|--:|\n")
        for (st, de), n in pairs.most_common():
            f.write("| `%s` | `%s` | %d |\n" % (st, de, n))
        f.write("\n全行: `%s`\n" % OUT_CSV.name)
    print("\n一覧: %s\n      %s" % (OUT_MD, OUT_CSV))

    if args.commit:
        n = 0
        for x in rows:
            r = db.execute("SELECT id, specs FROM products WHERE category=? AND product_id=?",
                           (x["category"], x["product_id"])).fetchone()
            if r is None:
                continue
            s = json.loads(r["specs"] or "{}")
            s["set_name_ebay"] = x["derived"]
            s["set_name_ebay_source"] = "jp_set_name_restore_20260821"
            db.execute("UPDATE products SET specs=?, updated_at=? WHERE id=?",
                       (json.dumps(s, ensure_ascii=False), NOW, r["id"]))
            n += 1
        db.commit()
        print("[OK] 適用 %d 行" % n)
    else:
        print("(report のみ — --commit で適用)")
    db.close()


if __name__ == "__main__":
    main()
