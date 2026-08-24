"""ポケモンの種別を、保存済の公式HTML の見出しから取り直す (21,982行).

## なぜ

取り込みが **カード名に「エネルギー」が入っているか**で種別を決めていた:

    if hp: Pokémon / elif "エネルギー" in name: Energy / else: Trainer

その結果、グッズの「エネルギー回収」「エネルギーつけかえ」「エネルギー転送」等
**127行が Energy** になっていた。Stage (2026-08-23) / タイプ (同日) と同じ形。

## どう直すか

公式は種別を見出しに出している: `<h2>グッズ</h2>`。ここから取る。
ポケモンには種別の見出しが無いので、進化段階の欄 (`span.type`) の有無で判定する。

## 公式の語彙は7つだけ (2026-08-25 実測 21,982枚)

    (ポケモン) 16576 / グッズ 1847 / サポート 1816 / 基本エネルギー 641 /
    ポケモンのどうぐ 475 / スタジアム 331 / 特殊エネルギー 296

**eBay の Card Type (Pokémon TCG) の11値と 1対1 で対応する**ので、そのまま採れる:

    ポケモン -> Pokémon         ポケモンのどうぐ -> Pokémon Tool
    グッズ   -> Trainer-Item    サポート        -> Trainer-Supporter
    スタジアム -> Trainer-Stadium
    基本エネルギー -> Energy-Basic  特殊エネルギー -> Energy-Special

これまでは `Pokémon` / `Trainer` / `Energy` の3値しか出しておらず、
`Trainer` は eBay の値としては在るが**粗い** (Item/Supporter/Stadium を潰していた)。

実行:
  python migrations/2026-08-25_pokemon_card_type_from_official.py           # dry-run
  python migrations/2026-08-25_pokemon_card_type_from_official.py --commit
"""
from __future__ import annotations

import argparse
import gzip
import html
import json
import os
import re
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scrapers"))
import api  # noqa: E402
from pokemon_tcg import _CARD_TYPE_TO_EBAY, _OFFICIAL_CARD_TYPES  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

RAW = Path(r"C:/dev/iMak_data/catalog/_raw/pokemon_tcg")
H2 = re.compile(r"<h2[^>]*>(.*?)</h2>", re.DOTALL)
SPAN = re.compile(r'<span class="type">([^<]*)</span>')
NOW = datetime.now().isoformat(timespec="seconds")


def official_type(card_id: str):
    p = RAW / f"{card_id}.html.gz"
    if not p.exists():
        return None
    h = gzip.open(p, "rt", encoding="utf-8", errors="ignore").read()
    for raw in H2.findall(h):
        v = re.sub(r"\s+", "", re.sub(r"<[^>]+>", "", html.unescape(raw))).strip()
        if v in _OFFICIAL_CARD_TYPES:
            return v
    return "ポケモン" if SPAN.search(h) else None


def run(commit: bool) -> None:
    db = sqlite3.connect(Path(api._DB_PATH))
    db.row_factory = sqlite3.Row
    rows = db.execute("SELECT id, product_id, source_url, specs FROM products "
                      "WHERE category='pokemon_tcg' AND source_url LIKE '%/card/%'").fetchall()
    pairs, updates, no_raw, undet = Counter(), [], 0, 0
    for r in rows:
        cid = str(r["source_url"]).rsplit("/", 1)[-1]
        jp = official_type(cid)
        if jp is None:
            if not (RAW / f"{cid}.html.gz").exists():
                no_raw += 1
            else:
                undet += 1
            continue
        want = _CARD_TYPE_TO_EBAY[jp]
        s = json.loads(r["specs"] or "{}")
        cur = s.get("card_type_ebay") or ""
        if cur == want:
            continue
        pairs[(cur or "(空)", want)] += 1
        s["card_type"] = jp
        s["card_type_ebay"] = want
        s["card_type_source"] = "official_h2_20260825"
        updates.append((json.dumps(s, ensure_ascii=False), NOW, r["id"]))

    print("=== 種別の取り直し (%s) ===" % ("APPLY" if commit else "DRY-RUN"))
    print("対象 %d 行 / 変わる %d 行 / raw なし %d / 判定不能 %d\n"
          % (len(rows), len(updates), no_raw, undet))
    print("%-14s %-20s %s" % ("今の値", "公式の見出し由来", "行数"))
    for (a, b), n in pairs.most_common(20):
        print("%-14s %-20s %d" % (a, b, n))
    if commit:
        db.executemany("UPDATE products SET specs=?, updated_at=? WHERE id=?", updates)
        db.commit()
        print("\n[OK] 適用 %d 行" % len(updates))
    else:
        print("\n(dry-run — --commit で適用)")
    db.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--commit", action="store_true")
    run(p.parse_args().commit)
