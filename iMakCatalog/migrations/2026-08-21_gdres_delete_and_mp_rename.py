#!/usr/bin/env python3
"""GD-RES を消して M-P を改名する.

決定: requests/2026-08-21_c36_hq_verdict_done_hq_reply.md [IMPLEMENT-GO]

## 1. GD-RES を削除
`RESOURCE` はガンダムの **カードの種類** (UNIT / PILOT / COMMAND / BASE / RESOURCE /
EX BASE / EX RESOURCE) であって、セット名ではない。実測:

    gundam の product_id 接頭辞  -> GD01/GD02/GD03/GD04/GD05/ST01-05/EB01/R
                                   ★GD-RES は 0件
    'Gundam Japanese Resource' を set_name_ebay に持つ行 -> 0件

セットでない値を Set の変換表に置いておく理由がないので消す。
★これは「未使用」ではなく「そもそも誤り」なので、他の未使用行 (残す) とは別扱い。

## 2. M-P を `Japanese Promo` -> `M-P: Mega Promos`
`Japanese Promo` は「日本のプロモ全般」としか読めず、`Sm-P` / `S-P` / `Sv-P` と
区別が付かない。畳み先が衝突しても気づけない。
eBay の書き方 (`Sm-P: Sun & Moon Promos` / `S-P: Sword & Shield Promos`) に沿わせる。

M-P が指すのは2つの公式セット (畳むこと自体は promo として正しい):
    ポケモンカードゲーム MEGA プロモカードパック第1弾  75件
    エクストラバトルの日                            7件

★eBay のリストにメガ期はまだ無いので **この綴りは自製** (HQ 決定 2026-08-21)。
  `Japanese Promo` も同じく自製で、より曖昧だったため、意味が分かる方を選んでいる。

実行:
  python migrations/2026-08-21_gdres_delete_and_mp_rename.py           # dry-run
  python migrations/2026-08-21_gdres_delete_and_mp_rename.py --commit
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
SRC_NOTE = "2026-08-21 HQ 決定・eBay 未収録のため自製"
VERIFY = "hq_verdict_20260821"

MP_NEW = "M-P: Mega Promos"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()
    db = sqlite3.connect(api._DB_PATH)
    db.row_factory = sqlite3.Row
    print("=== GD-RES 削除 / M-P 改名 (%s) ===" % ("APPLY" if args.commit else "DRY-RUN"))

    # --- 1. GD-RES: 消す前に「本当に使われていないか」を確かめる (fail-closed)
    print("\n--- 1. GD-RES の削除")
    used = db.execute("SELECT COUNT(*) FROM products WHERE category='gundam_tcg' "
                      "AND json_extract(specs,'$.set_name_ebay')='Gundam Japanese Resource'"
                      ).fetchone()[0]
    pids = db.execute("SELECT COUNT(*) FROM products WHERE product_id LIKE 'GD-RES%'").fetchone()[0]
    print("   set_name_ebay に使われている行: %d / GD-RES の product_id: %d" % (used, pids))
    if used or pids:
        print("   ✗ 使われている → 削除しない (fail-closed)")
    else:
        r = db.execute("SELECT id, source_value, ebay_value FROM ebay_filter_map "
                       "WHERE category='gundam_tcg' AND source_value='GD-RES'").fetchone()
        if r is None:
            print("   - 既に無い")
        else:
            print("   - 削除: %r -> %r" % (r["source_value"], r["ebay_value"]))
            if args.commit:
                db.execute("DELETE FROM ebay_filter_map WHERE id=?", (r["id"],))

    # --- 2. M-P の改名
    print("\n--- 2. M-P の改名 -> %r" % MP_NEW)
    rows = db.execute("SELECT id, field, source_value, ebay_value FROM ebay_filter_map "
                      "WHERE category='pokemon_tcg' AND ebay_value='Japanese Promo'").fetchall()
    for r in rows:
        print("   ~ %-9s %-46r %r -> %r"
              % (r["field"], r["source_value"], r["ebay_value"], MP_NEW))
        if args.commit:
            db.execute("UPDATE ebay_filter_map SET ebay_value=?, note=?, verified_at=?, "
                       "verify_source=? WHERE id=?",
                       (MP_NEW, SRC_NOTE, NOW, VERIFY, r["id"]))
    print("   対象 %d 行" % len(rows))

    # products 側で 'Japanese Promo' を焼いている行も揃える
    prod = db.execute("SELECT id, specs FROM products WHERE category='pokemon_tcg' "
                      "AND json_extract(specs,'$.set_name_ebay')='Japanese Promo'").fetchall()
    print("   products で 'Japanese Promo' を焼いている行: %d" % len(prod))
    if args.commit and prod:
        import json
        for r in prod:
            s = json.loads(r["specs"] or "{}")
            s["set_name_ebay"] = MP_NEW
            s["set_name_ebay_source"] = "mp_rename_20260821"
            db.execute("UPDATE products SET specs=?, updated_at=? WHERE id=?",
                       (json.dumps(s, ensure_ascii=False), NOW, r["id"]))

    if args.commit:
        db.commit()
        print("\n[OK] 適用")
    else:
        print("\n(dry-run — --commit で適用)")
    db.close()


if __name__ == "__main__":
    main()
