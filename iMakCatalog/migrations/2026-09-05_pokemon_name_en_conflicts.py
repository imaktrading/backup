# -*- coding: utf-8 -*-
"""同じカードに英語名が2つ以上ある 15件を1つにする (2026-09-05).

判定 (1丁目1番地): **①カタログのデータが誤り**。

## 何が起きていたか

2種類ある。

1. **別のカードの英語名が混ざっている** (兄弟デッキの取り違えと同じ形)

       基本水エネルギー  -> 'Bellibolt'(ハラバリー) が 7行
       博士の研究        -> 'Poké Kid'(ポケモンごっこ) が 1行
       ポケモンいれかえ  -> 'Poké Ball'(モンスターボール) が 1行

   見分け方: **その値が、別の日本語名の一番多い英語名になっている**なら混ざり込み。
   → その日本語名の一番多い英語名に直す。

2. **直訳が多数派になっている** (英語版の実際の名前が少数派)

       ハイパーボール    'Hyper Ball' 88行 vs 'Ultra Ball' 3行
       バトルサーチャー  'Battle Searcher' 13行 vs 'VS Seeker' 3行

   少数派は `bulbapedia_jp_deck_list_20260821` = **英語版の実物から取った値**で、
   多数派は辞書の直訳。PSA のラベルも英語版の名前で来るので、**少数派が正しい**。
   → 少数派に揃える。

## やらないこと

書き方だけの違い (`Mewtwo-EX` / `Mewtwo EX`、`Farfetch'd` / `Farfetch’d`) は
**多い方に寄せるだけ**。どちらも同じカードを指しているので直す価値は低いが、
「1カード1名」を保つために揃える。

実行:
  python migrations/2026-09-05_pokemon_name_en_conflicts.py [--commit]
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import defaultdict
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
# ワンピは `name` が英語のことがあるので、日本語名の列をカテゴリごとに指定する
CATS = {"pokemon_tcg": "name", "one_piece_tcg": "name_jp",
        "dragonball_scg": "name_jp", "gundam_tcg": "name_jp"}
# 英語版の実物から取った値が正しいもの (直訳が多数派になってしまっていた)
PREFER_MINORITY = {"ハイパーボール": "Ultra Ball", "バトルサーチャー": "VS Seeker"}


def run(cat: str, commit: bool) -> None:
    col = CATS[cat]
    db = sqlite3.connect(str(api._DB_PATH))
    db.row_factory = sqlite3.Row
    by: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    world: dict[str, int] = defaultdict(int)
    for jp, en in db.execute(
            f"SELECT {col}, name_en FROM products WHERE category=? "
            f"AND IFNULL({col},'')<>'' AND IFNULL(name_en,'')<>''", (cat,)):
        by[jp][en] += 1
        world[en] += 1
    # 同数のときは **カテゴリ全体で多く使われている方**を採る (書き方を1つに寄せる)
    top = {jp: max(v, key=lambda e: (v[e], world[e])) for jp, v in by.items()}
    owners = defaultdict(set)                    # 英語名 -> それを一番多く使う日本語名
    for jp, en in top.items():
        owners[en].add(jp)

    plan = []
    for jp, vals in by.items():
        if len(vals) < 2:
            continue
        want = PREFER_MINORITY.get(jp) or top[jp]
        for en, n in vals.items():
            if en == want:
                continue
            why = ("別カードの名前が混ざっている" if owners.get(en) and jp not in owners[en]
                   else "書き方の違い")
            plan.append((jp, en, want, n, why))

    print(f"=== 英語名の食い違い {cat} ({'APPLY' if commit else 'DRY-RUN'}) — {len(plan)}件 ===")
    done = 0
    for jp, en, want, n, why in sorted(plan, key=lambda x: -x[3]):
        print(f"    {jp:<14s} {en!r} ({n}行) -> {want!r}   [{why}]")
        if commit:
            done += db.execute(
                "UPDATE products SET name_en=?, name_en_source=?, updated_at=? "
                f"WHERE category=? AND {col}=? AND name_en=?",
                (want, "name_en_conflict_20260905", NOW, cat, jp, en)).rowcount
            db.commit()
    db.close()
    print("")
    print(f"{'適用' if commit else '(dry-run — --commit で適用)'} {done} 行")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cat", choices=sorted(CATS))
    ap.add_argument("--commit", action="store_true")
    a = ap.parse_args()
    for cat in ([a.cat] if a.cat else sorted(CATS)):
        run(cat, a.commit)


if __name__ == "__main__":
    main()
