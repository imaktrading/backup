#!/usr/bin/env python3
"""手つかずだった Manufacturer / Speciality を埋める.

2026-08-22 ユーザー指示「eBay の項目を網羅した枠を作り、正しい値を埋める。
目的はバイヤーの検索にできるだけ乗せること。値が正しいのは大前提」。

eBay の aspect 全35項目を並べたところ、RECOMMENDED なのに埋率0%が6項目あった。
うち **根拠を持って埋められる2つ** を入れる。

## Manufacturer (eBay 711値 / RECOMMENDED)
category から一意に決まる。綴りは eBay の一覧で実在確認済。
    pokemon_tcg   -> The Pokémon Company
    one_piece_tcg -> Bandai
    dragonball_scg-> Bandai
    gundam_tcg    -> Bandai
    yugioh_tcg    -> Konami

## Speciality (eBay 12値 / RECOMMENDED)
ポケモンの仕様名 (EX / GX / V / VMAX / TAG TEAM / BREAK / LEGEND / PRIME / MEGA)。
**カード名の末尾一致だけ**で決める。名前の途中に 'ex' を含むカードへの誤爆を避けるため。

★VSTAR は eBay の Speciality 一覧に**無い**ので空欄のままにする。
  V に寄せると別の仕様を名乗ることになる (2026-08-22 実測: VSTAR 102行)。
★ポケモン以外はこの語彙を持たないので入れない。

## 埋めないと決めた項目 (念のため)
  Age Level    CPSC の関係で出さない (ユーザー確定)
  Autographed  サイン入りの取り扱いが無い (ユーザー確定)
  Finish       現物依存 (2026-08-22 確定)

実行:
  python migrations/2026-08-22_manufacturer_speciality.py           # dry-run
  python migrations/2026-08-22_manufacturer_speciality.py --commit
"""
from __future__ import annotations

import argparse
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
MASTER = Path(r"C:\dev\iMak_data\catalog\_input\ebay_aspects_183454_latest.json")
CATS = ("pokemon_tcg", "one_piece_tcg", "dragonball_scg", "gundam_tcg", "yugioh_tcg")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()

    A = json.loads(MASTER.read_text(encoding="utf-8"))["aspects"]
    man_ok = set(A["Manufacturer"]["all"])
    spe_ok = set(A["Speciality"]["all"])

    db = sqlite3.connect(api._DB_PATH)
    db.row_factory = sqlite3.Row
    print("=== Manufacturer / Speciality を埋める (%s) ===" % ("APPLY" if args.commit else "DRY-RUN"))

    man_hits, spe_hits, updates = Counter(), Counter(), []
    for cat in CATS:
        for r in db.execute("SELECT id, category, name_en, specs FROM products WHERE category=?", (cat,)):
            s = json.loads(r["specs"] or "{}")
            changed = False

            if not (s.get("manufacturer_ebay") or "").strip():
                m = api.derive_manufacturer(cat)
                if m and m in man_ok:            # eBay の一覧に在ることを確認してから入れる
                    s["manufacturer_ebay"] = m
                    man_hits[(cat, m)] += 1
                    changed = True

            if not (s.get("speciality_ebay") or "").strip():
                sp = api.derive_speciality(cat, r["name_en"])
                if sp and sp in spe_ok:
                    s["speciality_ebay"] = sp
                    spe_hits[(cat, sp)] += 1
                    changed = True

            if changed:
                s["aspect_fill_source"] = "derive_20260822"
                updates.append((json.dumps(s, ensure_ascii=False), NOW, r["id"]))

    print("\n--- Manufacturer")
    for (cat, v), n in man_hits.most_common():
        print("   %-16s -> %-24r %6d" % (cat, v, n))
    print("\n--- Speciality (ポケモンのみ / 末尾一致)")
    for (cat, v), n in spe_hits.most_common():
        print("   %-16s -> %-12r %6d" % (cat, v, n))
    print("\n更新する行 %d" % len(updates))

    if args.commit and updates:
        db.executemany("UPDATE products SET specs=?, updated_at=? WHERE id=?", updates)
        db.commit()
        print("[OK] 適用")
    elif not args.commit:
        print("(dry-run — --commit で適用)")
    db.close()


if __name__ == "__main__":
    main()
