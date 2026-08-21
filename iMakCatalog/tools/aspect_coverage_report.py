#!/usr/bin/env python3
"""出品に出している全項目を eBay の値リストと突合して A/B/C に仕分ける.

2026-08-22。ユーザー指示「eBay の一覧を把握して、それに近づけるのが答え」。

## 仕分け
  A = そのまま eBay の一覧に在る        → 触らない
  B = 同じものが**別の綴り**で在る       → eBay の綴りを採れる (伸びしろ)
  C = eBay に無い                       → そのまま (自由入力。絞り込みには乗らない)

## ★B の判定は「完全に同じと言い切れる時」だけ
似ているだけで寄せると別物として出品される
(2026-08-21 実測: GX Battle Boost (SM4+) を Ex Battle Boost (EXバトルブースト BW期) に
寄せかけた = 別セット)。ここでは次の3つしか B と見なさない:

  1. 大文字小文字だけの違い
  2. eBay 側が弾番号 prefix を付けているだけ ('Eevee Heroes' -> 'S6a: Eevee Heroes')
  3. 記号/空白だけの違い (ハイフン・コロン・全角半角)

**語が入れ替わる / 単語が増減するものは B にしない。** 人が1件ずつ見る C に落とす。

## Game 別に絞る
Set / Card Type は eBay が Game 別の内訳を返すので、そちらだけを候補にする。
全ゲーム混在の all を使うと 'Promo Cards' が Final Fantasy の 'FF: Promo Cards' に寄る。

実行:
  python tools/aspect_coverage_report.py                 # 全カテゴリ
  python tools/aspect_coverage_report.py --cat pokemon_tcg
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import api  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

MASTER = Path(r"C:\dev\iMak_data\catalog\_input\ebay_aspects_183454_latest.json")
OUT_MD = Path(r"C:\dev\iMak_data\catalog\requests\2026-08-22_aspect_coverage_report.md")
NOW = datetime.now().isoformat()

GAME_OF = {"pokemon_tcg": "Pokémon TCG", "one_piece_tcg": "One Piece CCG",
           "dragonball_scg": "Dragon Ball Super Card Game"}
CATS = ("pokemon_tcg", "one_piece_tcg", "dragonball_scg", "gundam_tcg")

# (表示名, specs のキー / ':name_en' は products 列, eBay の aspect 名)
FIELDS = [
    ("Set",         "set_name_ebay",     "Set"),
    ("Rarity",      "rarity_ebay",       "Rarity"),
    ("Card Name",   ":name_en",          "Card Name"),
    ("Character",   "character_name",    "Character"),
    ("Card Type",   "card_type_ebay",    "Card Type"),
    ("Language",    "language",          "Language"),
    ("Card Size",   "card_size_ebay",    "Card Size"),
    ("Illustrator", "illustrator",       "Illustrator"),
    ("Finish",      "finish",            "Finish"),
    ("Game",        "game_ebay",         "Game"),
]

PREFIX_RE = re.compile(r"^[A-Za-z]{1,6}[\d+]*[A-Za-z+]*:\s*")


def squash(s):
    """記号・空白を落として比較用に潰す."""
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def build_index(values):
    """潰した名前 -> [eBay 値]. 弾番号 prefix も外した形で引けるようにする."""
    idx = defaultdict(list)
    for v in values:
        idx[squash(v)].append(v)
        bare = PREFIX_RE.sub("", v)
        if bare != v:
            idx[squash(bare)].append(v)
    return idx


def classify_value(v, pool, idx):
    """A / B(=採るべき綴り) / C を返す."""
    if v in pool:
        return "A", None
    cands = idx.get(squash(v)) or []
    # 候補が1つに定まる時だけ B。複数あるなら人が見る
    if len(set(cands)) == 1:
        return "B", cands[0]
    return "C", None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cat", action="append")
    args = ap.parse_args()
    cats = args.cat or list(CATS)

    A = json.loads(MASTER.read_text(encoding="utf-8"))["aspects"]
    lines = ["# 出品項目 × eBay 値リスト 突合レポート\n",
             f"\n生成: {NOW} / 照合相手: `{MASTER.name}`\n",
             "\n- **A** = そのまま eBay の一覧に在る (触らない)\n",
             "- **B** = 同じものが別の綴りで在る (**eBay の綴りを採れる = 伸びしろ**)\n",
             "- **C** = eBay に無い (そのまま。絞り込みには乗らない)\n",
             "- 空欄 = 値を入れていない行\n"]

    for cat in cats:
        game = GAME_OF.get(cat)
        rows = list(api._connect().execute(
            "SELECT name_en, specs FROM products WHERE category=?", (cat,)))
        n = len(rows)
        print(f"\n===== {cat}  ({n:,} 行)")
        lines.append(f"\n## {cat} ({n:,} 行)\n\n")
        lines.append("| 項目 | 空欄 | A | B | C | B の例 |\n|---|--:|--:|--:|--:|---|\n")
        print("%-13s %7s %7s %7s %7s   %s" % ("項目", "空欄", "A", "B", "C", "B の例"))

        for label, key, asp in FIELDS:
            node = A.get(asp)
            if not node:
                continue
            pool_list = node["by_game"].get(game) or node["all"]
            pool, idx = set(pool_list), build_index(pool_list)
            cnt = Counter()
            b_examples = Counter()
            for r in rows:
                v = (r["name_en"] if key == ":name_en"
                     else (json.loads(r["specs"] or "{}") or {}).get(key)) or ""
                v = str(v).strip()
                if not v:
                    cnt["blank"] += 1
                    continue
                st, prop = classify_value(v, pool, idx)
                cnt[st] += 1
                if st == "B":
                    b_examples[(v, prop)] += 1
            ex = ""
            if b_examples:
                (a_, b_), c_ = b_examples.most_common(1)[0]
                ex = f"`{a_}` → `{b_}` ({c_}行)"
            print("%-13s %7d %7d %7d %7d   %s"
                  % (label, cnt["blank"], cnt["A"], cnt["B"], cnt["C"], ex))
            lines.append("| %s | %d | %d | **%d** | %d | %s |\n"
                         % (label, cnt["blank"], cnt["A"], cnt["B"], cnt["C"], ex))

    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text("".join(lines), encoding="utf-8")
    print(f"\nレポート: {OUT_MD}")


if __name__ == "__main__":
    main()
