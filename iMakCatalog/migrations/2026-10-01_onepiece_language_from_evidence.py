# -*- coding: utf-8 -*-
"""ワンピの `language` を **証拠 (絵の置き場)** から決め直す (2026-10-01).

依頼: `requests/2026-10-01_onepiece_language_redecide_go.md` [IMPLEMENT-GO]
元: `requests/2026-10-01_onepiece_language_en_on_jp_rows.md` (HQ)

## 判定: ① カタログの値が誤り

`language='en'` の **1,778行のうち、英語版の絵 (`card_image/OP-EN/`) を持つ行は 0**。
1,570行は日本語版の絵を持ち、336行は日本公式サイト由来。公式も取り直して確かめた:

    https://www.onepiece-cardgame.com/.../EB03-053_p2.png  -> 200
    files.bandai-tcg-plus.com/card_image/OP-EN/EB03-053.png -> 403 (英語版は無い)

根因: `detect_language()` が **bandai の EN/JA 2つの一覧の突き合わせだけ**で決めていて、
日本公式サイトに在ることを数えていなかった。突き合わせの鍵 (画像ファイル名由来) が
外れると「JA に無い」= `en` になる。= `en` は「英語版」ではなく「**鍵が外れた**」の意味。

## 新しい基準 (証拠から。無ければ空欄 = fail-closed)

    英語版の絵がある (card_image/OP-EN/)            -> en      (日本語版の絵もあれば both)
    日本語版の絵がある / 日本公式サイト由来          -> both    (英語版の一覧にも在った行)
                                                      ja      (英語版の一覧に無かった行)
    どちらの証拠も無い                              -> None

★`en` だった行は「英語版の一覧に在った」ことだけは確か (だから en が付いた) ので、
  日本語版の証拠があれば `both` になる。絵も出所も無い 208行は `None` に落とす。

## 控え

書き換える前に **DB をファイルごと控える** + 変える行の前の値を JSON で残す
(`_backups/` と `_backups/..._language_rows.json`)。

実行: python migrations/2026-10-01_onepiece_language_from_evidence.py [--commit]
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

DB = Path("C:/dev/iMak_data/catalog/products.sqlite")
BK = Path("C:/dev/iMak_data/catalog/_backups")
CATEGORY = "one_piece_tcg"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def evidence(images) -> tuple[bool, bool]:
    """(英語版の絵があるか, 日本語版の絵があるか)."""
    en = ja = False
    for u in images or []:
        if not isinstance(u, str):
            continue
        if "card_image/OP-EN/" in u:
            en = True
        elif ("card_image/OP-JA/" in u or "onepiece-cardgame.com" in u
                or "_official_images" in u):
            ja = True
    return en, ja


# ★日本語版だと確かめてある出所 (CLAUDE.md「公式カードリストに無いカードを登録してよいか」)。
#   絵が PSA スラブの実写だったり、絵が無かったりするので、置き場だけでは拾えない。
#   実例: EB02-003_CH01 (集英社の付録) / ST13-003_7E01 (セブンイレブン) /
#         OP06-068_AC01 (Admirable Collection)。ここを見ないと 4行を空欄に落とす
_JP_CONFIRMED = ("opcg_official", "slab_confirmed", "web_confirmed", "shueisha")


def decide(language: str | None, source: str, images) -> str | None:
    """証拠から `language` を決める。`language` は「今 入っている値」(= 一覧の在処の手がかり)."""
    en_img, ja_img = evidence(images)
    from_jp_site = any(k in (source or "") for k in _JP_CONFIRMED)
    ja_side = ja_img or from_jp_site
    in_en_list = language in ("en", "both")       # その値が付いた = 英語版の一覧に在った
    if en_img:
        return "both" if ja_side else "en"
    if ja_side:
        return "both" if in_en_list else "ja"
    return None                                   # 証拠が無い -> 空欄 (fail-closed)


def plan(conn) -> list[tuple[int, str, str | None, str | None]]:
    out = []
    for rid, pid, src, lang, im in conn.execute(
            "SELECT id, product_id, source, language, images FROM products WHERE category=?",
            (CATEGORY,)):
        try:
            images = json.loads(im or "[]")
        except ValueError:
            images = []
        new = decide(lang, src or "", images)
        if new != lang:
            out.append((rid, pid, lang, new))
    return out


def main() -> None:
    commit = "--commit" in sys.argv
    conn = sqlite3.connect(str(DB), timeout=180)
    rows = plan(conn)
    print(f"=== language を証拠から決め直す ({'APPLY' if commit else 'DRY-RUN'}) ===")
    moves: dict[tuple, int] = {}
    for _, _, old, new in rows:
        moves[(old, new)] = moves.get((old, new), 0) + 1
    for (old, new), n in sorted(moves.items(), key=lambda x: -x[1]):
        print(f"  {str(old):5} -> {str(new):5}  {n}行")
    print(f"  合計 {len(rows)}行")
    if not commit:
        conn.close()
        print("\n(dry-run — --commit で適用)")
        return

    BK.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    # ★WAL の未反映分を先に畳んでから file コピー (CLAUDE.md の決まり)
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    db_bk = BK / f"products_{stamp}_before_language.sqlite"
    shutil.copy2(DB, db_bk)
    rows_bk = BK / f"products_{stamp}_before_language_rows.json"
    rows_bk.write_text(json.dumps(
        [{"id": r, "product_id": p, "language": o} for r, p, o, _ in rows],
        ensure_ascii=False), encoding="utf-8")
    print(f"\n控え: {db_bk.name} ({db_bk.stat().st_size // 2**20}MB) / {rows_bk.name}")

    conn.executemany("UPDATE products SET language=? WHERE id=?",
                     [(new, rid) for rid, _, _, new in rows])
    conn.commit()
    left = len(plan(conn))
    counts = dict(conn.execute(
        "SELECT language, count(*) FROM products WHERE category=? GROUP BY language",
        (CATEGORY,)).fetchall())
    conn.close()
    print(f"適用した。新基準でまだ違う行 {left}件")
    print("今の内訳:", counts)


if __name__ == "__main__":
    main()
