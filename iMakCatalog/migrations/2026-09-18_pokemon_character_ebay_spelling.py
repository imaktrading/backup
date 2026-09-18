# -*- coding: utf-8 -*-
"""Character を eBay の一覧に在る綴りに寄せる (2026-09-18).

判定 (1丁目1番地): **①カタログのデータ**。Character の綴りを決めるのはカタログ。
依頼: `iMak_data/catalog/requests/2026-09-18_character_normalize_implement.md` [IMPLEMENT-GO]

## 何をするか (依頼の 1 / 2 / 3)

1. **綴りのゆれ** — 正規化 (英数字だけにする) すると一覧の値と一致する物を、一覧の綴りに直す。
   `Ho-oh` → `Ho-Oh` / `Unown [!]` → `Unown` / `Nidoran♀` → `Nidoran (♀)`。
   ★♀♂ は **記号で行き先を決める**。正規化だけだと ♀ と ♂ が同じキーに落ちて入れ替わる。
2. **形の違い** — `Mewtwo-EX` → Character `Mewtwo` + Speciality `EX`。
   末尾の形を外した名前が**一覧に在る時だけ**直す (fail-closed)。
   形は `speciality_ebay` に入れる (空の行だけ。既に入っている行は触らない)。
3. **キャラクターでない値を空欄にする** — `DON!! Card` / `Energy Marker` / `Basic * Energy`。
   カード種別であってキャラではなく、Set / Card Type 側に同じ情報が出ている。
   ★これはカタログの判断 (依頼は「そちらの判断で」)。対象は**この明示の一覧だけ**で、
     カード種別からの一括判定はしない (サポートの絵柄にキャラが居る行を巻き込むため)。

## 戻せるようにしてあること

直した行には `character_name_prev` (直す前の値) と `character_name_source` を残す。

## 一覧の出どころ

`_input/ebay_aspects_183454_latest.json` (`tools/fetch_ebay_aspects.py` で取得)。
**保存値で判断しないため、取得日が古い時は止まる**。

実行:
  python migrations/2026-09-18_pokemon_character_ebay_spelling.py            # dry-run
  python migrations/2026-09-18_pokemon_character_ebay_spelling.py --commit
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import api  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ASPECTS = Path(r"C:/dev/iMak_data/catalog/_input/ebay_aspects_183454_latest.json")
TAG = "ebay_character_spelling_20260918"
MAX_AGE_DAYS = 7

# 末尾の「形」。Character から外して Speciality に移す。
FORM_RE = re.compile(r"[\s\-]*(ex|EX|GX|VMAX|VSTAR|V-UNION|V|BREAK|LV\.X)$")
# eBay の Speciality はこの綴り (一覧に無い VSTAR / V-UNION も真実なのでそのまま出す)
FORM_TO_SPECIALITY = {"ex": "EX", "EX": "EX", "GX": "GX", "V": "V", "VMAX": "VMAX",
                      "VSTAR": "VSTAR", "V-UNION": "V-UNION", "BREAK": "BREAK", "LV.X": "Level Up"}
# 3. キャラクターでない値 (明示の一覧のみ)
NOT_CHARACTER_RE = re.compile(r"^(DON!! Card|Energy Marker|Basic \w+ Energy)$")


def norm(v: str) -> str:
    return re.sub(r"[^a-z0-9]", "", v.lower())


def load_allowed() -> set[str]:
    d = json.loads(ASPECTS.read_text(encoding="utf-8"))
    fetched = d.get("fetched")
    age = (date.today() - date.fromisoformat(fetched)).days if fetched else 999
    if age > MAX_AGE_DAYS:
        raise SystemExit(f"eBay の一覧が {age}日前 ({fetched})。"
                         "`python tools/fetch_ebay_aspects.py` で取り直してから実行してください")
    vals = set(d["aspects"]["Character"]["all"])
    print(f"eBay Character 一覧 {len(vals)}値 (取得 {fetched})")
    return vals


def plan(db: sqlite3.Connection, allowed: set[str]):
    """(rowid, 旧値, 新値 or None, 形) を返す. 新値 None = 空欄にする."""
    by_norm: dict[str, list[str]] = {}
    for v in allowed:
        by_norm.setdefault(norm(v), []).append(v)

    out = []
    # ★遊戯王は出品していないので触らない (ユーザー確定 2026-09-03)
    for rid, cat, specs in db.execute("SELECT id, category, specs FROM products "
                                      "WHERE specs LIKE '%character_name%' "
                                      "AND category <> 'yugioh_tcg'"):
        s = json.loads(specs or "{}")
        ch = (s.get("character_name") or "").strip()
        if not ch or ch in allowed:
            continue

        # 3. キャラクターでない値 → 空欄
        if NOT_CHARACTER_RE.match(ch):
            out.append((rid, cat, ch, None, None, s))
            continue

        # 1. 綴りのゆれ (正規化すると一覧の値と一致)
        cands = by_norm.get(norm(ch), [])
        if cands:
            hit = None
            if len(cands) == 1:
                hit = cands[0]
            else:
                # ♀♂ のように記号で別れる物は、記号を持つ候補を選ぶ (正規化では区別できない)
                marks = [m for m in ("♀", "♂") if m in ch]
                if len(marks) == 1:
                    same = [c for c in cands if marks[0] in c]
                    hit = same[0] if len(same) == 1 else None
            if hit and hit != ch:
                out.append((rid, cat, ch, hit, None, s))
            continue

        # 2. 形の違い (末尾を外した名前が一覧に在る時だけ)
        m = FORM_RE.search(ch)
        if not m:
            continue
        base = FORM_RE.sub("", ch).strip()
        if base in allowed:
            out.append((rid, cat, ch, base, FORM_TO_SPECIALITY.get(m.group(1)), s))
    return out


def main(commit: bool) -> None:
    allowed = load_allowed()
    db = api._connect()
    rows = plan(db, allowed)

    kinds = Counter()
    for _, cat, old, new, form, _ in rows:
        kinds[("空欄にする" if new is None else ("形を外す" if form else "綴りを直す"), cat)] += 1
    for (k, cat), n in sorted(kinds.items(), key=lambda x: -x[1]):
        print(f"  {k:10} {cat:15} {n:5}行")
    print(f"  合計 {len(rows)}行")
    for _, _, old, new, form, _ in rows[:8]:
        print(f"    例: {old!r} → {new!r}" + (f" + Speciality {form!r}" if form else ""))

    if not commit:
        print("dry-run (書いていない)")
        return

    now = datetime.now().isoformat(timespec="seconds")
    spec_filled = 0
    for rid, _, old, new, form, s in rows:
        s["character_name_prev"] = old
        s["character_name_source"] = TAG
        if new is None:
            s.pop("character_name", None)
        else:
            s["character_name"] = new
        if form and not s.get("speciality_ebay"):
            s["speciality_ebay"] = form
            spec_filled += 1
        db.execute("UPDATE products SET specs=?, updated_at=? WHERE id=?",
                   (json.dumps(s, ensure_ascii=False), now, rid))
    db.commit()
    print(f"書いた {len(rows)}行 / Speciality を埋めた {spec_filled}行")

    left = plan(db, allowed)
    print(f"直した後に同じ基準で数え直し: 残り {len(left)}行")


if __name__ == "__main__":
    main("--commit" in sys.argv)
