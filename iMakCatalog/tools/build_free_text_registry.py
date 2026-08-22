#!/usr/bin/env python3
"""ルール② の自由入力セット名の登録簿を作る (2026-08-23 新設).

`set_name_ebay` に入ってよい値は2つだけ:
  ① eBay master (Game 別) に在る値
  ② **この登録簿に在る値** (日本語セット名の英語表記)

どちらでもない値は監査 §0b が毎日拾う。**見た目の条件で確認しない**ための仕組み。
(2026-08-23: 'Swsh で始まる値' という条件で確認して「0行」と報告したが、
 `Sun & Moon—Celestial Storm` 等が漏れていた。条件を思いつけるかに依存する確認は必ず漏れる)

★英語版シリーズ名で始まる値は **登録簿に入れない** (ここで弾く)。

実行:
  python tools/build_free_text_registry.py            # 現状から作り直す
  python tools/build_free_text_registry.py --check    # 作り直さず、違反だけ見る
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import api  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

MASTER = Path(r"C:/dev/iMak_data/catalog/_input/ebay_aspects_183454_latest.json")
OUT = ROOT / "ebay_filter_map" / "_free_text_set_values.yaml"
GAME_OF = {"pokemon_tcg": "Pokémon TCG", "one_piece_tcg": "One Piece CCG",
           "dragonball_scg": "Dragon Ball Super Card Game", "gundam_tcg": None}
# 英語版シリーズ名で始まる値は登録できない (ルール③)
BANNED = re.compile(r"^(Sun & Moon|Scarlet & Violet|Sword & Shield|Swsh|Black & White|"
                    r"Diamond & Pearl|HeartGold|Platinum)\s*[—\-–:]", re.I)
NL = chr(10)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    by_game = json.loads(MASTER.read_text(encoding="utf-8"))["aspects"]["Set"]["by_game"]
    db = api._connect()
    free = collections.defaultdict(collections.Counter)
    jp = {}
    banned = []
    for r in db.execute("SELECT category, set_name_official, specs FROM products "
                        "WHERE category IN ('pokemon_tcg','one_piece_tcg','dragonball_scg','gundam_tcg')"):
        v = (json.loads(r["specs"] or "{}").get("set_name_ebay") or "").strip()
        if not v or v in set(by_game.get(GAME_OF[r["category"]] or "", [])):
            continue
        if BANNED.match(v):
            banned.append((r["category"], v, r["set_name_official"]))
            continue
        free[r["category"]][v] += 1
        jp.setdefault((r["category"], v), r["set_name_official"] or "")

    if banned:
        c = collections.Counter((b[0], b[1]) for b in banned)
        print("❌ 英語版シリーズ名で始まる値が使われています (登録できません):")
        for (cat, v), n in c.most_common(20):
            print(f"   {cat}: {v} × {n}")
        print("   → 変換表を直してから作り直してください")
        sys.exit(1)

    if args.check:
        print("違反なし")
        return

    lines = [
        "# ルール② で入れている「eBay の一覧に無い自由入力」の登録簿 (自動生成)",
        "# 生成: tools/build_free_text_registry.py",
        "#",
        "# set_name_ebay に入ってよいのは ① eBay master に在る値 か ② ここに在る値 だけ。",
        "# どちらでもない値は監査 §0b が毎日拾う。**見た目の条件で確認しない**ための仕組み。",
        "# 英語版シリーズ名で始まる値は生成時に弾く (ルール③)。",
        "",
        "values:",
    ]
    n = 0
    for cat in GAME_OF:
        if not free[cat]:
            continue
        lines.append(f"  # ── {cat} ──")
        for v, cnt in sorted(free[cat].items(), key=lambda x: -x[1]):
            lines += [f"  - value: {json.dumps(v, ensure_ascii=False)}",
                      f"    category: {cat}", f"    rows: {cnt}"]
            if jp.get((cat, v)):
                lines.append(f"    jp_set: {json.dumps(jp[(cat, v)], ensure_ascii=False)}")
            n += 1
    OUT.write_text(NL.join(lines) + NL, encoding="utf-8")
    print(f"登録簿を書きました: {OUT}  ({n} 値)")


if __name__ == "__main__":
    main()
