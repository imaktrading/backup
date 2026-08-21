#!/usr/bin/env python3
"""手つかずだった Features を埋める (eBay 39値 / RECOMMENDED / MULTI).

2026-08-22。eBay の aspect を網羅した枠を作った結果、Features が 0% だったので埋める。
**根拠のある手がかりだけを使う**。推測しない。

## 使う手がかりと行き先 (eBay の値に実在することを確認して入れる)

| こちらの手がかり                       | eBay の Features |
|---|---|
| `variant_type = 'promo'`              | `Promo` |
| `set_name_ebay` に 'Promo' を含む      | `Promo` |
| `variant_type = 'alt_art'`            | `Alternative Art` |
| `features` に 'Alt Art'/'Alternative Art' | `Alternative Art` |
| `features` に 'Full Art'               | `Full Art` |
| `variant_type = 'starter_deck'`        | `Starter Deck` |

Features は **MULTI** (複数値可) なので、当てはまるものを全部入れる。

## 使わない手がかり
- **遊戯王の `variant_type`** ('common' / 'super_rare' 等) は**レアリティ**であって
  Features ではない。入れない。
- ポケモンの `features = ['Art Card']` (857行) は eBay に 'Art Card' が**無い**。
  近い値 ('Altered/Custom Art' 等) に寄せない。空欄のまま。
- `variant_type='premium_booster'` (884行) も eBay に該当が無い。

★「似ているから寄せる」をしない。2026-08-21 に GX Battle Boost を Ex Battle Boost に
  寄せかけた事故と同じ型になる。

実行:
  python migrations/2026-08-22_features_fill.py           # dry-run
  python migrations/2026-08-22_features_fill.py --commit
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
# 遊戯王は variant_type がレアリティなので対象外
CATS = ("pokemon_tcg", "one_piece_tcg", "dragonball_scg", "gundam_tcg")


def derive_features(specs):
    """specs から eBay の Features を決める. 該当なしは空リスト."""
    out = []
    vt = (specs.get("variant_type") or "").strip().lower()
    raw = specs.get("features")
    raw_l = [str(x).strip().lower() for x in raw] if isinstance(raw, list) else []
    set_ebay = (specs.get("set_name_ebay") or "").lower()

    if vt == "promo" or "promo" in raw_l or "promo" in set_ebay:
        out.append("Promo")
    if vt == "alt_art" or "alt art" in raw_l or "alternative art" in raw_l:
        out.append("Alternative Art")
    if "full art" in raw_l:
        out.append("Full Art")
    if vt == "starter_deck":
        out.append("Starter Deck")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()

    ok = set(json.loads(MASTER.read_text(encoding="utf-8"))["aspects"]["Features"]["all"])
    db = sqlite3.connect(api._DB_PATH)
    db.row_factory = sqlite3.Row
    print("=== Features を埋める (%s) ===" % ("APPLY" if args.commit else "DRY-RUN"))

    hits, updates = Counter(), []
    for cat in CATS:
        for r in db.execute("SELECT id, specs FROM products WHERE category=?", (cat,)):
            s = json.loads(r["specs"] or "{}")
            if (s.get("features_ebay") or ""):
                continue
            vals = [v for v in derive_features(s) if v in ok]   # eBay に在るものだけ
            if not vals:
                continue
            for v in vals:
                hits[(cat, v)] += 1
            s["features_ebay"] = ", ".join(dict.fromkeys(vals))   # MULTI = カンマ区切り
            s["features_ebay_source"] = "derive_20260822"
            updates.append((json.dumps(s, ensure_ascii=False), NOW, r["id"]))

    for (cat, v), n in hits.most_common():
        print("   %-16s -> %-18r %6d" % (cat, v, n))
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
