#!/usr/bin/env python3
"""綴りだけを eBay の一覧に合わせる (中身は変えない).

2026-08-22。突合レポートの **B群** = 「同じものが eBay に別の綴りで在る」行。
記号・大小・アクセントを潰して**一意に定まる時だけ**採る。

  例: `Pokégear 3.0` -> `PokéGear 3.0` / `Farfetch’d` -> `Farfetch'd` /
      `match` -> `Match` / `HeartGold & SoulSilver` -> `Heartgold & Soulsilver`

## 守ること
- **候補が2つ以上ある行は触らない** (人が見る)。
- 潰して一致しないもの (= 別物) は触らない。`GX Battle Boost` -> `Ex Battle Boost`
  のような「似ているから寄せる」はここでは起きない (潰しても一致しないため)。
- 中身が変わる置換はしない。変わるのは綴りだけ。
- **こちらの2つ以上の値が eBay の同じ値に潰れる時は、両方とも触らない**。
  実例: `Nidoran♂` と `Nidoran♀` はどちらも eBay の `Nidoran` に潰れる。寄せると
  別のカードが同じ名前になり、区別が消える (= 情報を失う)。

実行:
  python migrations/2026-08-22_ebay_spelling_align.py           # dry-run
  python migrations/2026-08-22_ebay_spelling_align.py --commit
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import api  # noqa: E402
sys.path.insert(0, str(ROOT / "tools"))
from aspect_coverage_report import build_index, classify_value  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ex / EX / GX は **時代の違い**を表す (XY 期の `Charizard-EX` と SV 期の `Charizard ex` は
# 別のカード)。大小が違う寄せは、刷られている名前と違う名前を出すことになるのでしない。
_MARKER_RE = re.compile(r"[-\s]?(ex|gx)$", re.IGNORECASE)


def marker_case_differs(cur: str, new: str) -> bool:
    a, b = _MARKER_RE.search(cur.strip()), _MARKER_RE.search(new.strip())
    return bool(a and b and a.group(1) != b.group(1))


NOW = datetime.now().isoformat(timespec="seconds")
SOURCE = "ebay_spelling_20260822"
MASTER = Path(r"C:\dev\iMak_data\catalog\_input\ebay_aspects_183454_latest.json")
CATS = ("pokemon_tcg", "one_piece_tcg", "dragonball_scg", "gundam_tcg")
GAME_OF = {"pokemon_tcg": "Pokémon TCG", "one_piece_tcg": "One Piece CCG",
           "dragonball_scg": "Dragon Ball Super Card Game", "gundam_tcg": None}

# eBay aspect -> (こちらの置き場所, products 列か specs キーか)
TARGETS = [("Set", "set_name_ebay", "specs"),
           ("Character", "character_name", "specs"),
           ("Illustrator", "illustrator", "specs"),
           ("Card Name", "name_en", "column")]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()

    aspects = json.loads(MASTER.read_text(encoding="utf-8"))["aspects"]
    db = sqlite3.connect(api._DB_PATH)
    db.row_factory = sqlite3.Row
    pairs, updates, skipped, marker_skip = Counter(), {}, Counter(), Counter()
    # 1回目: 潰れ先が衝突する組を洗い出す (こちらの別々の値 -> eBay の同じ値)
    collide = set()
    seen = {}
    for asp, key, where in TARGETS:
        a = aspects[asp]
        for cat in CATS:
            pool = set(a["by_game"].get(GAME_OF[cat] or "", []) or a["all"])
            idx = build_index(pool)
            for r in db.execute("SELECT name_en, specs FROM products WHERE category=?", (cat,)):
                s_ = json.loads(r["specs"] or "{}")
                cur = (r["name_en"] if where == "column" else s_.get(key)) or ""
                if not str(cur).strip():
                    continue
                verdict, new = classify_value(str(cur), pool, idx)
                if verdict != "B":
                    continue
                prev = seen.setdefault((asp, new), str(cur))
                if prev != str(cur):
                    collide.add((asp, new))

    for asp, key, where in TARGETS:
        a = aspects[asp]
        for cat in CATS:
            pool = set(a["by_game"].get(GAME_OF[cat] or "", []) or a["all"])
            idx = build_index(pool)
            for r in db.execute("SELECT id, name_en, specs FROM products WHERE category=?", (cat,)):
                s = json.loads(r["specs"] or "{}")
                cur = (r["name_en"] if where == "column" else s.get(key)) or ""
                if not str(cur).strip():
                    continue
                verdict, new = classify_value(str(cur), pool, idx)
                if verdict != "B" or new == cur:
                    continue
                if (asp, new) in collide:      # 情報を失う寄せは行わない
                    skipped[(asp, new)] += 1
                    continue
                if marker_case_differs(str(cur), new):   # ex/EX は時代が違う = 別カード
                    marker_skip[(str(cur), new)] += 1
                    continue
                pairs[(asp, str(cur), new)] += 1
                st = updates.setdefault(r["id"], {"specs": s, "name_en": r["name_en"]})
                if where == "column":
                    st["name_en"] = new
                else:
                    st["specs"][key] = new
                st["specs"].setdefault("ebay_spelling_aligned", [])
                if asp not in st["specs"]["ebay_spelling_aligned"]:
                    st["specs"]["ebay_spelling_aligned"].append(asp)
                st["specs"]["ebay_spelling_source"] = SOURCE

    if skipped:
        print("見送り (寄せると別物が同じ名前になる): "
              + ", ".join(f"{a}/{v}:{n}" for (a, v), n in skipped.most_common()))
        print()
    if marker_skip:
        print("見送り (ex/EX の大小は時代が違う = 別カード): %d 組 %d 行  例 %s"
              % (len(marker_skip), sum(marker_skip.values()),
                 ", ".join(f"{a}->{b}" for a, b in list(marker_skip)[:3])))
        print()
    print("=== 綴りを eBay に合わせる (%s) ===" % ("APPLY" if args.commit else "DRY-RUN"))
    print("触る行 %d / 置換の組 %d\n" % (len(updates), len(pairs)))
    print("%-12s %-40s %-40s %s" % ("項目", "今の綴り", "eBay の綴り", "行数"))
    for (asp, cur, new), n in pairs.most_common(60):
        print("%-12s %-40s %-40s %d" % (asp, cur[:39], new[:39], n))
    if len(pairs) > 60:
        print("... 他 %d 組" % (len(pairs) - 60))

    if args.commit and updates:
        db.executemany("UPDATE products SET specs=?, name_en=?, updated_at=? WHERE id=?",
                       [(json.dumps(v["specs"], ensure_ascii=False), v["name_en"], NOW, i)
                        for i, v in updates.items()])
        db.commit()
        print("\n[OK] 適用 %d 行" % len(updates))
    elif not args.commit:
        print("\n(dry-run — --commit で適用)")
    db.close()


if __name__ == "__main__":
    main()
