"""rarity 'SS' の 12 行に eBay 値を入れる (LEGEND / Gold Star).

指示: ユーザー 2026-08-13「正式名が取れ次第、足します → いつ取るの?」

**公式ポケカは rarity の正式名を持っていない**ことを実測で確認 (2026-08-13):
  https://www.pokemon-card.com/card-search/details.php/card/{4010,25027,50084,47998}
  → rarity は `<img src=".../rarity/ic_rare_ss.gif">` のアイコン画像のみ。
     alt も title も無く、長形名はサイト上のどこにも存在しない。
  つまり「公式の正式名を待つ」は永久に来ない = 待ち方針が誤りだった。

ただし 'SS' の 12 行は **カード名そのものに designation が印刷されている**ので、
推測せずに決められる (= 公式表記を読んでいるだけ):
  - "Ho-Oh LEGEND" / "Lugia LEGEND" …      → rarity_ebay = 'LEGEND'   (9件)
  - "Flareon Star" / "Vaporeon ☆" …        → rarity_ebay = 'Gold Star' (3件)

filter_map (code → value) では表せない (同じ 'SS' が 2 値に分かれる = カード名依存) ため、
本 migration で行ごとに入れる。eBay Rarity facet は FREE_TEXT なので master 非収載でも
出力可 (Leader / Legend Rare と同じ扱い)。

残る 17 行 (MUR 6 / BWR 2 / C2 1 / U2 1 / one_piece の SP 系 7) は
カード名に手がかりが無く、「eBay でどう名乗るか」の findability 判断なので
HQ に 1 行 sign-off を依頼する (requests/2026-08-13_rarity_17rows_naming_decision.md)。

実行:
  python migrations/2026-08-13_pokemon_ss_legend_goldstar.py           # dry-run
  python migrations/2026-08-13_pokemon_ss_legend_goldstar.py --commit  # 適用
"""
from __future__ import annotations

import argparse
import json
import shutil
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

DB_PATH = Path(api._DB_PATH)
NOW = datetime.now().isoformat()
CAT = "pokemon_tcg"
SRC_TAG = "rarity_ss_by_card_name_20260813"


def classify(name_en: str | None, name: str | None) -> str | None:
    """カード名に印刷されている designation を読む (推測はしない)."""
    hay = f"{name_en or ''} {name or ''}"
    if "LEGEND" in hay.upper():
        return "LEGEND"
    if "Star" in hay or "☆" in hay:
        return "Gold Star"
    return None


def process(commit: bool) -> int:
    print(f"=== pokemon rarity 'SS' → LEGEND / Gold Star ({'APPLY' if commit else 'DRY-RUN'}) ===")
    if commit:
        backup = DB_PATH.with_suffix(f".sqlite.bak_ss_{datetime.now():%Y%m%d%H%M%S}")
        shutil.copy2(DB_PATH, backup)
        print(f"backup: {backup.name}\n")

    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    updates, skipped = [], []

    for r in db.execute("SELECT id, product_id, name, name_en, specs FROM products "
                        "WHERE category = ?", (CAT,)):
        specs = json.loads(r["specs"] or "{}")
        if specs.get("rarity") != "SS" or specs.get("rarity_ebay"):
            continue
        val = classify(r["name_en"], r["name"])
        if val is None:
            skipped.append((r["product_id"], r["name_en"]))
            continue
        print(f"  {r['product_id']:<18} {str(r['name_en'])[:30]:<30} → {val}")
        specs["rarity_ebay"] = val
        specs["rarity_ebay_source"] = SRC_TAG
        updates.append((json.dumps(specs, ensure_ascii=False), NOW, r["id"]))

    print(f"\n対象 {len(updates)} 行 / 判別できず据置 {len(skipped)} 行")
    for pid, n in skipped:
        print(f"  ⚠️ 据置 (fail-closed): {pid} {n!r}")

    if commit:
        db.executemany("UPDATE products SET specs = ?, updated_at = ? WHERE id = ?", updates)
        db.commit()
        print("✅ 適用")
    else:
        print("(dry-run — --commit で適用)")
    db.close()
    return len(updates)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--commit", action="store_true")
    process(p.parse_args().commit)


if __name__ == "__main__":
    main()
