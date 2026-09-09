"""ガンダム / ドラゴンボール(FW) を公式 API と突き合わせる (2026-09-03 新設).

One Piece 版・ポケモン版と同じ考え方。**保存値ではなく、今その場で公式 API を叩く**。

公式 (bandai-tcg-plus) の `user/card/list` は、その game の全カードを JSON で返す:

    {"card_number": "GD01-093", "card_name": "...", "card_set_id": ..., "image_url": ...}

見るのは2つ:
    A. 公式に在るのに catalog に無い (券面番号で照合)  → 取り込み漏れ
    B. カード名が違う                                  → parse ミス or 公式の訂正

★券面番号は catalog の product_id の頭 (`GD01-093_p1` → `GD01-093`) と対応する。
★fail-closed: API が取れなければ「差分0」ではなく **取得失敗** として数える。
★JA (日本語) 側を正とする。当社が出すのは日本語版なので。

使い方:
    python tools/official_drift_bandai.py                 # 両方
    python tools/official_drift_bandai.py --cat gundam_tcg
"""
from __future__ import annotations

import argparse
import html
import json
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

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

STATE = Path("C:/dev/iMak_data/catalog/_official_drift_bandai_state.json")
# category -> (scraper モジュール名, JA の game_title_id)
GAMES = {
    "gundam_tcg": ("gundam_tcg", 15),
    "dragonball_scg": ("dragonball_scg", 11),
}


def _clean(t: str) -> str:
    """比較前に書き方だけ畳む (実体参照・タグ・全角記号)."""
    t = re.sub(r"<[^>]+>", "", html.unescape(t or ""))
    return t.replace("＆", "&").replace("　", " ").replace("’", "'").strip()


def official(cat: str) -> list[dict]:
    mod_name, game_id = GAMES[cat]
    mod = __import__(mod_name)
    out, seen = [], set()
    for c in mod.list_all_cards(game_id):
        no = (c.get("card_number") or "").strip()
        name = _clean(c.get("card_name") or "")
        if not no or (no, name) in seen:
            continue
        seen.add((no, name))
        out.append({"no": no, "name": name})
    return out


def check(cat: str) -> dict:
    cards = official(cat)
    if not cards:
        return {"cat": cat, "error": "公式 API が0件を返した"}
    db = sqlite3.connect(str(api._DB_PATH), timeout=120)
    db.row_factory = sqlite3.Row
    try:
        rows = db.execute(
            "SELECT product_id, name, name_jp FROM products WHERE category=?", (cat,)).fetchall()
    finally:
        db.close()
    by_no: dict[str, list] = {}
    for r in rows:
        base = (r["product_id"] or "").split("_")[0]
        by_no.setdefault(base, []).append(r)

    missing, name_ng = [], []
    for c in cards:
        rs = by_no.get(c["no"])
        if not rs:
            missing.append(c)
            continue
        names = {_clean(r["name"] or "") for r in rs} | {_clean(r["name_jp"] or "") for r in rs}
        if c["name"] and c["name"] not in names:
            name_ng.append((c, rs[0]["product_id"], sorted(x for x in names if x)[:2]))
    return {"cat": cat, "fetched": len(cards), "rows": len(rows),
            "missing": missing, "name_ng": name_ng}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cat", choices=sorted(GAMES), help="カテゴリを指定")
    a = ap.parse_args()
    cats = [a.cat] if a.cat else sorted(GAMES)

    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    now = datetime.now().isoformat(timespec="seconds")
    print(f"=== 公式との突合 (bandai / {', '.join(cats)}) {now} ===")
    total = ng = fail = 0
    for cat in cats:
        try:
            res = check(cat)
        except Exception as e:
            fail += 1
            print(f"  ✗ {cat} 取得失敗: {e}")
            continue
        if res.get("error"):
            fail += 1
            print(f"  ✗ {cat} {res['error']}")
            continue
        n = len(res["missing"]) + len(res["name_ng"])
        total += res["fetched"]
        ng += n
        print(f"  {'OK ' if n == 0 else '★NG'} {cat:16s} 公式 {res['fetched']:5d}枚 "
              f"/ catalog {res['rows']:5d}行 / 差分 {n}")
        for c in res["missing"][:6]:
            print(f"      [欠落] {c['no']:14s} {c['name']}")
        for c, pid, got in res["name_ng"][:6]:
            print(f"      [名前] {pid:18s} 公式={c['name']!r} catalog={got}")
        state[cat] = {"at": now, "ng": n}
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    print("")
    if fail:
        print(f"⚠️ 取得できなかった {fail} 件 (= 検査できていない。正常ではない)")
    print(f"突合 {total}枚 / 差分 {ng}件")


if __name__ == "__main__":
    main()
