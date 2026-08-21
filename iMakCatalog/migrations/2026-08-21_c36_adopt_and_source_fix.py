#!/usr/bin/env python3
"""C 36語の裏取り結果を反映 (引き当て3 + 元データの誤り2 + 全角空白の取りこぼし1).

決定: requests/2026-08-21_c36_hq_verdict.md [IMPLEMENT-GO]
      出品くんが36語を eBay 2,290語に**部分一致で**引き直して確認したもの。

## ① eBay に在ったので引き当てる
  Sm Promo              -> Sm-P: Sun & Moon Promos            (4行)
  Tag Team GX All Stars -> Sm12a: Tag Team GX: Tag All Stars   (2行)
  Mewtwo ex Starter Deck-> Sv: Mewtwo Ex Terastal Starter Set  (1行)

  ★eBay のプロモは `<コード>-P` 形式 (ADV-P / BW-P / Sm-P / S-P / Sv-P)。
  `Future Flash` / `Remix Bout` は 2026-08-21 の照合で引き当て済のため対象外。

## ② 変換表の source_value が壊れている — products の公式名と字が違う
  誤 'ブースターパック 迫り来る強敵[FB06]'   -> 正 'ブースターパック 迫り来る脅威[FB06]'
  誤 'ブースターパック 迫り高き戦闘力 [FB08]' -> 正 'ブースターパック 誇り高き戦闘民族 [FB08]'

  変換先 (Rivals Clash / Saiyan's Pride) は公式英語名と一致していて正しい。
  **日本語の元表記だけが誤っていた**ので、公式名で引いても当たらず C に落ちていた。

## ③ 全角空白の取りこぼし
  products には 'ブースターパック　迫り来る脅威[FB06]' (全角空白) が **137行**ある。
  半角の行は15行しかない。両方を source に持たせる。

★寄せてはいけないもの (出品くん検証。触らない):
  Edition Beta ≠ 'Limited Edition - Beta' (マジック) / Dual Impact ≠ Force of Will /
  Rivals Clash ≠ 'Rising Rivals' (ポケモン) / Saiyan's Pride ≠ 'Assault of the Saiyans'
  = GX Battle Boost と Ex Battle Boost を寄せかけた時と同じ型。

実行:
  python migrations/2026-08-21_c36_adopt_and_source_fix.py           # dry-run
  python migrations/2026-08-21_c36_adopt_and_source_fix.py --commit
"""
from __future__ import annotations

import argparse
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

NOW = datetime.now().isoformat()
VERIFY = "ebay_partial_match_recheck+hq_c36_verdict_20260821"

# 旧 ebay_value -> eBay の綴り
ADOPT = {
    "Sm Promo": "Sm-P: Sun & Moon Promos",
    "Tag Team GX All Stars": "Sm12a: Tag Team GX: Tag All Stars",
    "Mewtwo ex Starter Deck": "Sv: Mewtwo Ex Terastal Starter Set",
}

# (誤った source_value, 正しい source_value)
SRC_FIX = [
    ("ブースターパック 迫り来る強敵[FB06]", "ブースターパック 迫り来る脅威[FB06]"),
    ("ブースターパック 迫り高き戦闘力 [FB08]", "ブースターパック 誇り高き戦闘民族 [FB08]"),
]

# 全角空白版の追加 (source_value, ebay_value)
SRC_ADD = [
    ("dragonball_scg", "set", "ブースターパック　迫り来る脅威[FB06]", "Rivals Clash"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()
    db = sqlite3.connect(api._DB_PATH)
    db.row_factory = sqlite3.Row
    print("=== C36 反映 (%s) ===" % ("APPLY" if args.commit else "DRY-RUN"))

    print("\n--- ① eBay の綴りに引き当て")
    n1 = 0
    for old, new in ADOPT.items():
        rows = db.execute("SELECT id, category, field, source_value FROM ebay_filter_map "
                          "WHERE ebay_value=?", (old,)).fetchall()
        if not rows:
            print("  - %r 該当なし (既に引き当て済?)" % old)
            continue
        for r in rows:
            print("  ~ %-9s %-46r %r -> %r" % (r["field"], r["source_value"], old, new))
            if args.commit:
                db.execute("UPDATE ebay_filter_map SET ebay_value=?, status='A', verified_at=?, "
                           "verify_source=? WHERE id=?", (new, NOW, VERIFY, r["id"]))
            n1 += 1

    print("\n--- ② source_value の誤りを直す (公式名と字が違っていた)")
    n2 = 0
    for bad, good in SRC_FIX:
        r = db.execute("SELECT id, category, field, ebay_value FROM ebay_filter_map "
                       "WHERE source_value=?", (bad,)).fetchone()
        if r is None:
            print("  - %r 該当なし" % bad)
            continue
        n = db.execute("SELECT COUNT(*) FROM products WHERE set_name_official=?", (good,)).fetchone()[0]
        print("  ~ %r\n      -> %r  (products に %d 行)" % (bad, good, n))
        if n == 0:
            print("      ✗ products に無い → skip (fail-closed)")
            continue
        if args.commit:
            db.execute("UPDATE ebay_filter_map SET source_value=?, verified_at=?, verify_source=? "
                       "WHERE id=?", (good, NOW, VERIFY, r["id"]))
        n2 += 1

    print("\n--- ③ 全角空白版の追加 (取りこぼし)")
    n3 = 0
    for cat, field, src, ev in SRC_ADD:
        exists = db.execute("SELECT 1 FROM ebay_filter_map WHERE category=? AND field=? "
                            "AND source_value=?", (cat, field, src)).fetchone()
        n = db.execute("SELECT COUNT(*) FROM products WHERE set_name_official=?", (src,)).fetchone()[0]
        if exists:
            print("  - 既に在る: %r" % src)
            continue
        print("  + %r -> %r  (products に %d 行)" % (src, ev, n))
        if n == 0:
            print("      ✗ products に無い → skip")
            continue
        if args.commit:
            db.execute("INSERT INTO ebay_filter_map (category, field, source_value, ebay_value, "
                       "note, created_at, status, verified_at, verify_source) VALUES (?,?,?,?,?,?,?,?,?)",
                       (cat, field, src, ev, "2026-08-21 全角空白版の取りこぼし", NOW, "B", NOW, VERIFY))
        n3 += 1

    print("\n引き当て %d / source 修正 %d / 追加 %d" % (n1, n2, n3))
    if args.commit:
        db.commit()
        print("[OK] 適用")
    else:
        print("(dry-run — --commit で適用)")
    db.close()


if __name__ == "__main__":
    main()
