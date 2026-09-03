"""取り込んだ行に「出品に出る値」を付ける — 取り込みの最後の1手 (2026-09-03 新設).

## なぜ要るか

scraper が入れるのは **公式の生値だけ**。出品くんが読む `*_ebay` は付かない。
そのまま置くと「カタログには在るのに出せない」状態になり、テストも落ちる。
2026-09-02 (OP-17 178行) と 2026-09-03 (FB11 125行) で**2回続けて同じことをやった**ので、
カテゴリ非依存の1コマンドにする。

    python tools/finish_ingest.py --cat dragonball_scg          # 何が付くか見る
    python tools/finish_ingest.py --cat dragonball_scg --commit

## 付ける値 (すべて既存の決まりから導出。推測しない)

    game_ebay / manufacturer_ebay      api.derive_game_ebay / derive_manufacturer (category 定数)
    card_size_ebay / language / country_of_origin_ebay   定数
    rarity_ebay                        api.derive_rarity_ebay (変換表)
    card_type_ebay                     既存行が使っている対応をそのまま (新語彙は作らない)
    set_name_ebay                      api.derive_set_name_ebay (変換表)

★変換表に無いものは **空欄のまま** (fail-closed)。何が引けなかったかは最後に一覧で出す。
  そこが「変換表に1行足す」作業の入口になる。
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

NOW = datetime.now().isoformat(timespec="seconds")
CONSTANTS = {"card_size_ebay": "Standard", "language": "Japanese",
             "country_of_origin_ebay": "Japan"}


def _card_type_map(db, cat: str) -> dict:
    """そのカテゴリの既存行が使っている card_type → card_type_ebay の対応."""
    m: dict[str, Counter] = {}
    for (specs,) in db.execute(
            "SELECT specs FROM products WHERE category=? "
            "AND IFNULL(json_extract(specs,'$.card_type_ebay'),'')<>''", (cat,)):
        s = json.loads(specs or "{}")
        raw = str(s.get("card_type") or s.get("Card Type") or "").strip()
        val = str(s.get("card_type_ebay") or "").strip()
        if raw and val:
            m.setdefault(raw, Counter())[val] += 1
    return {k: v.most_common(1)[0][0] for k, v in m.items()}


def run(cat: str, commit: bool) -> int:
    db = sqlite3.connect(str(api._DB_PATH))
    db.row_factory = sqlite3.Row
    ctmap = _card_type_map(db, cat)
    rows = db.execute(
        "SELECT id, product_id, set_name_official, specs FROM products "
        "WHERE category=? AND ("
        "  IFNULL(json_extract(specs,'$.game_ebay'),'')='' OR"
        "  IFNULL(json_extract(specs,'$.set_name_ebay'),'')='' OR"
        "  IFNULL(json_extract(specs,'$.card_type_ebay'),'')='' OR"
        "  IFNULL(json_extract(specs,'$.rarity_ebay'),'')='')", (cat,)).fetchall()
    print(f"=== 仕上げ {cat} ({'APPLY' if commit else 'DRY-RUN'}) — 対象 {len(rows)}行 ===")
    game, maker = api.derive_game_ebay(cat), api.derive_manufacturer(cat)
    filled, unmapped = Counter(), Counter()
    for r in rows:
        s = json.loads(r["specs"] or "{}")
        before = json.dumps(s, sort_keys=True)
        if game and not s.get("game_ebay"):
            s["game_ebay"] = game
            filled["game_ebay"] += 1
        if maker and not s.get("manufacturer_ebay"):
            s["manufacturer_ebay"] = maker
            filled["manufacturer_ebay"] += 1
        for k, v in CONSTANTS.items():
            if not s.get(k):
                s[k] = v
                filled[k] += 1
        raw_ct = str(s.get("card_type") or s.get("Card Type") or "").strip()
        if raw_ct and not s.get("card_type_ebay"):
            if raw_ct in ctmap:
                s["card_type_ebay"] = ctmap[raw_ct]
                filled["card_type_ebay"] += 1
            else:
                unmapped[f"card_type={raw_ct!r}"] += 1
        raw_r = str(s.get("rarity") or s.get("Rarity") or "").strip()
        if raw_r and not s.get("rarity_ebay"):
            v = api.derive_rarity_ebay(cat, raw_r)
            if v:
                s["rarity_ebay"] = v
                filled["rarity_ebay"] += 1
            else:
                unmapped[f"rarity={raw_r!r}"] += 1
        if not s.get("set_name_ebay"):
            v = api.derive_set_name_ebay(cat, r["set_name_official"], r["product_id"])
            if v:
                s["set_name_ebay"] = v
                s["set_name_ebay_source"] = f"finish_ingest_{NOW[:10].replace('-', '')}"
                filled["set_name_ebay"] += 1
            else:
                unmapped[f"set={r['set_name_official']!r}"] += 1
        if commit and json.dumps(s, sort_keys=True) != before:
            db.execute("UPDATE products SET specs=?, updated_at=? WHERE id=?",
                       (json.dumps(s, ensure_ascii=False), NOW, r["id"]))
    if commit:
        db.commit()
    db.close()

    for k, v in filled.most_common():
        print(f"  + {k:24s} {v}行")
    if unmapped:
        print(f"  ★変換表に無い (空欄のまま。ここに1行足す):")
        for k, v in unmapped.most_common(10):
            print(f"      {v:5d}行  {k}")
    print("")
    print(f"{'適用' if commit else '(dry-run — --commit で適用)'}")
    return len(unmapped)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cat", required=True)
    ap.add_argument("--commit", action="store_true")
    a = ap.parse_args()
    sys.exit(0 if run(a.cat, a.commit) == 0 else 1)


if __name__ == "__main__":
    main()
