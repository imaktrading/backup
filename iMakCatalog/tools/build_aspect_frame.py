#!/usr/bin/env python3
"""eBay の aspect を全部カバーする変換表の「枠」を作る.

2026-08-22 ユーザー指示:
  「eBay のフィルタ項目を取れるようになった。その項目を網羅した変換表の枠を作る。
    その次に正しい値を埋める。目的はバイヤーの検索にできるだけ乗せること。
    値が正しいものは大前提」

## なぜ枠が要るか
これまで変換表は `set` / `set_code` / `rarity` の **3 field しか無かった**。
eBay は 183454 に **35 aspect** を持つのに、残りは変換表を通らず素通しだった。
素通しだと、ズレていても**誰も気づけない** (2026-08-22 実測: ワンピの Character は
96% 埋めているのに eBay の値と一致するのは 19行だけだった)。

**枠がある = 測れる = 埋める対象が見える。** それが枠を先に作る理由。

## 出力
1. `ebay_filter_map/_frame_<取得日>.yaml`
   全 aspect の枠。各 aspect に:
     ebay_aspect / required / usage / mode / eBay の値数 / こちらの source (specs のキー)
     / 現状の埋まり具合 / 変換表の有無
2. 画面に一覧 (どれが手つかずか)

## 埋める優先度の考え方 (目的 = 検索に乗せる)
  必須 > RECOMMENDED > OPTIONAL
  値リストが大きい (= バイヤーが絞り込みに使う) ものを優先
  ★ただし **正しい値を入れられるものだけ**。根拠が無いものは空欄のまま (大前提)

実行:
  python tools/build_aspect_frame.py
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import api  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

MASTER = Path(r"C:\dev\iMak_data\catalog\_input\ebay_aspects_183454_latest.json")
CATS = ("pokemon_tcg", "one_piece_tcg", "dragonball_scg", "gundam_tcg", "yugioh_tcg")

# eBay aspect -> こちらの source (specs のキー / ':name_en' は products 列 / None = 未対応)
SOURCE_OF = {
    "Game": "game_ebay",
    "Set": "set_name_ebay",
    "Rarity": "rarity_ebay",
    "Card Name": ":name_en",
    "Character": "character_name",
    "Card Type": "card_type_ebay",
    "Card Number": "card_number_text",
    "Language": "language",
    "Card Size": "card_size_ebay",
    "Illustrator": "illustrator",
    "Finish": "finish",
    "HP": "hp_ebay",
    "Attack/Power": "attack_power_ebay",
    "Defense/Toughness": "defense_toughness_ebay",
    "Attribute/MTG:Color": "color_ebay",
    "Manufacturer": None,
    "Features": None,
    "Speciality": None,
    "Material": None,
    "Stage": "stage",
    "Year Manufactured": None,
    "Country of Origin": None,
    "Vintage": None,
    "Autographed": None,
    "Graded": None,
    "Grade": None,
    "Professional Grader": None,
    "Certification Number": None,
    "Card Condition": None,
}

# 変換表が既に持っている field
HAS_TABLE = {"Set": "set / set_code", "Rarity": "rarity"}


def main():
    doc = json.loads(MASTER.read_text(encoding="utf-8"))
    aspects = doc["aspects"]
    fetched = doc.get("fetched", "?")

    # 現状の埋まり具合
    fill = {a: Counter() for a in aspects}
    total = Counter()
    db = api._connect()
    for cat in CATS:
        for r in db.execute("SELECT name_en, specs FROM products WHERE category=?", (cat,)):
            s = json.loads(r["specs"] or "{}")
            total[cat] += 1
            for asp, key in SOURCE_OF.items():
                if not key or asp not in aspects:
                    continue
                v = (r["name_en"] if key == ":name_en" else s.get(key)) or ""
                if str(v).strip():
                    fill[asp][cat] += 1
    n_all = sum(total.values())

    rows = []
    for asp, a in aspects.items():
        c = a["constraint"]
        src = SOURCE_OF.get(asp)
        filled = sum(fill[asp].values()) if asp in fill else 0
        rows.append({
            "aspect": asp,
            "required": bool(c.get("required")),
            "usage": c.get("usage"),
            "mode": c.get("mode"),
            "values": len(a["all"]),
            "by_game": len(a.get("by_game") or {}),
            "source": src,
            "filled": filled,
            "pct": (filled * 100 // n_all) if n_all else 0,
            "table": HAS_TABLE.get(asp),
        })

    # 優先度: 必須 > RECOMMENDED > OPTIONAL、次に値リストの大きさ
    order = {"RECOMMENDED": 0, "OPTIONAL": 1}
    rows.sort(key=lambda x: (not x["required"], order.get(x["usage"], 9), -x["values"]))

    print("=== eBay aspect 全 %d 項目 (取得 %s) / 全 %s 行 ===\n" % (len(rows), fetched, f"{n_all:,}"))
    print("%-24s %-5s %-12s %7s %6s %-18s %-12s" %
          ("aspect", "必須", "usage", "値数", "埋率", "こちらの source", "変換表"))
    print("-" * 92)
    for r in rows:
        print("%-24s %-5s %-12s %7d %5d%% %-18s %-12s" %
              (r["aspect"], "★" if r["required"] else "", r["usage"] or "",
               r["values"], r["pct"], r["source"] or "**未対応**", r["table"] or "無し"))

    # 枠 yaml
    out = ROOT / "ebay_filter_map" / ("_frame_%s.yaml" % date.today().isoformat())
    lines = ["# eBay aspect を網羅した変換表の枠 (自動生成 / 手で編集しない)\n",
             "# 生成: %s   取得マスタ: %s (fetched %s)\n" % (date.today().isoformat(), MASTER.name, fetched),
             "# 目的: バイヤーの検索にできるだけ乗せる。**正しい値であることが大前提**。\n",
             "# 根拠の無いものは空欄のままにする (推測で埋めない)。\n\n",
             "aspects:\n"]
    for r in rows:
        lines.append("  - ebay_aspect: %s\n" % json.dumps(r["aspect"], ensure_ascii=False))
        lines.append("    required: %s\n" % str(r["required"]).lower())
        lines.append("    usage: %s\n" % (r["usage"] or "null"))
        lines.append("    mode: %s\n" % (r["mode"] or "null"))
        lines.append("    ebay_value_count: %d\n" % r["values"])
        lines.append("    ebay_by_game: %d\n" % r["by_game"])
        lines.append("    source: %s\n" % (json.dumps(r["source"], ensure_ascii=False)
                                           if r["source"] else "null   # 未対応"))
        lines.append("    filled_pct: %d\n" % r["pct"])
        lines.append("    filter_map_field: %s\n" % (json.dumps(r["table"], ensure_ascii=False)
                                                    if r["table"] else "null   # 変換表なし"))
    out.write_text("".join(lines), encoding="utf-8")
    print("\n枠: %s" % out)

    todo = [r for r in rows if r["source"] is None and r["usage"] == "RECOMMENDED"]
    print("\n=== 手つかず かつ RECOMMENDED (優先して埋める候補) ===")
    for r in todo:
        print("   %-24s %6d値  mode=%s" % (r["aspect"], r["values"], r["mode"]))


if __name__ == "__main__":
    main()
