#!/usr/bin/env python3
"""Year Manufactured を変換表の year から埋める (eBay 37値 / SELECTION_ONLY).

2026-08-22。枠を作ったら Year Manufactured が 15% しか埋まっておらず、pokemon は 0件
だった。一方 `ebay_filter_map/*.yaml` には弾ごとの `year:` が既に 178行入っている。
**写すだけで埋まる**ので写す。

## 使う手がかり (この2つだけ)
| 手がかり | 引き方 |
|---|---|
| `set` の year   | set_name_official 完全一致 |
| `set_code` の year | product_id の頭 (SM-P-052 → SM-P も見る) |

## やらないこと
- **年の推測をしない**。旧 migration (2026-05-30) は `OP07 → 2022 + (n-1)//4` のような
  概算を持っているが、ここでは使わない。変換表に year が無い弾は**空欄のまま**。
- 既に値がある行は**触らない**。
- eBay の Year Manufactured は SELECTION_ONLY (1990〜2026)。範囲外は書かない。

実行:
  python migrations/2026-08-22_release_year_from_filter_map.py           # dry-run
  python migrations/2026-08-22_release_year_from_filter_map.py --commit
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import api  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

NOW = datetime.now().isoformat(timespec="seconds")
SOURCE = "filter_map_year_20260822"
MASTER = Path(r"C:\dev\iMak_data\catalog\_input\ebay_aspects_183454_latest.json")
YAML_OF = {"pokemon_tcg": "pokemon", "one_piece_tcg": "one_piece",
           "dragonball_scg": "dragonball", "gundam_tcg": "gundam"}


def _year_maps(cat: str):
    d = yaml.safe_load((ROOT / "ebay_filter_map" / f"{YAML_OF[cat]}.yaml").read_text(encoding="utf-8"))
    by_set = {e["source"]: str(e["year"]) for e in (d.get("set") or []) if e.get("year")}
    by_code = {str(e["source"]).lower(): str(e["year"]) for e in (d.get("set_code") or []) if e.get("year")}
    return by_set, by_code


def _derive(pid: str, set_official: str, by_set: dict, by_code: dict):
    if set_official and set_official in by_set:
        return by_set[set_official]
    if pid and "-" in pid:
        heads = [pid.split("-", 1)[0]]
        if pid.count("-") >= 2:                      # 'SM-P-052' -> 'SM-P'
            heads.insert(0, pid.rsplit("-", 1)[0])
        for h in heads:
            if h.lower() in by_code:
                return by_code[h.lower()]
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    # ★gundam / dragonball は既存値と変換表の year が食い違う (どちらも過去の概算が出所)。
    #   例: GD01 は DB 2025 / yaml 2024、FB01 は DB 2023 / yaml 2024。
    #   公式で裏を取るまで書かない。既定から外す。
    ap.add_argument("--categories", default="pokemon_tcg,one_piece_tcg")
    # 旧 migration (2026-05-30) が概算で入れた値を、実発売日ベースの変換表で置き換える。
    #   概算由来の行は release_year_source を持たないので、それを目印にする。
    ap.add_argument("--fix-estimates", action="store_true",
                    help="概算で入っている値 (release_year_source 無し) を変換表の year で直す")
    args = ap.parse_args()

    ok_years = set(json.loads(MASTER.read_text(encoding="utf-8"))["aspects"]["Year Manufactured"]["all"])
    db = sqlite3.connect(api._DB_PATH)
    db.row_factory = sqlite3.Row
    per_cat, years, updates, out_of_list, fixed = Counter(), Counter(), [], Counter(), Counter()

    for cat in [c for c in YAML_OF if c in args.categories.split(",")]:
        by_set, by_code = _year_maps(cat)
        for r in db.execute("SELECT id, product_id, set_name_official, specs FROM products WHERE category=?", (cat,)):
            s = json.loads(r["specs"] or "{}")
            cur = str(s.get("release_year") or "").strip()
            if cur and not (args.fix_estimates and not s.get("release_year_source")):
                continue
            y = _derive(r["product_id"], r["set_name_official"], by_set, by_code)
            if not y:
                continue
            if y not in ok_years:                     # eBay の選択肢に無い年は書かない
                out_of_list[y] += 1
                continue
            if cur == y:
                continue
            if cur:
                fixed[f"{cur}->{y}"] += 1
            s["release_year"] = y
            s["release_year_source"] = SOURCE
            per_cat[cat] += 1
            years[y] += 1
            updates.append((json.dumps(s, ensure_ascii=False), NOW, r["id"]))

    print("=== Year Manufactured を変換表の year から埋める (%s) ===" % ("APPLY" if args.commit else "DRY-RUN"))
    print("埋める行 %d\n" % len(updates))
    for cat, n in per_cat.most_common():
        print("  %-16s %6d" % (cat, n))
    print("\n  年の内訳: %s" % ", ".join(f"{y}:{n}" for y, n in sorted(years.items())))
    if fixed:
        print("  概算からの是正: %s" % ", ".join(f"{k}:{n}" for k, n in fixed.most_common()))
    if out_of_list:
        print("  eBay の選択肢に無い年で見送り: %s" % dict(out_of_list))

    if args.commit and updates:
        db.executemany("UPDATE products SET specs=?, updated_at=? WHERE id=?", updates)
        db.commit()
        print("\n[OK] 適用 %d 行" % len(updates))
    elif not args.commit:
        print("\n(dry-run — --commit で適用)")
    db.close()


if __name__ == "__main__":
    main()
