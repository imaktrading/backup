"""別デッキのカード名が name_en に入っていた 54行を直す (2026-09-04).

判定 (1丁目1番地): **①カタログのデータが誤り** → catalog 側で直す。
HQ 回答 `hq/requests/2026-09-04_pokemon_deck_code_collision_response.md` の手順1。

## 何が起きたか

公式は兄弟デッキに同じ弾コード・同じ番号を振る (`SCS-001` が リザードンデッキにも
オーロンゲデッキにも在る)。catalog の鍵は1つなので、後から来たデッキの取り込みが
**同じ行を更新**し、`name_en` だけ上書きした。結果:

    SCS-001  name_jp='アブソル' (オーロンゲデッキ) / name_en='Charizard V' (リザードンデッキ)

1行の中で別のカードが混ざっている。出品すると **英語名と絵が食い違う** = 誤出品。

## 直し方

`scrapers/pokemon_name_translation.resolve_name_en()` (PokeAPI 辞書 + 規則) で
`name_jp` から引き直す。**表記ゆれ (`Farfetch'd` の引用符, `Dedenne GX` の hyphen) は
触らない** — 英数字だけ取り出して比べ、**別の語**になっている行だけ直す。

実行:
  python migrations/2026-09-04_name_en_cross_deck_fix.py [--commit]
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scrapers"))
import api  # noqa: E402
import pokemon_name_translation as T  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

NOW = datetime.now().isoformat(timespec="seconds")


def _norm(x: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (x or "").lower())


def run(commit: bool) -> None:
    d1, d2 = T.load_pokeapi_dict(), T.load_api_dict()
    db = sqlite3.connect(Path(api._DB_PATH))
    db.row_factory = sqlite3.Row
    rows = db.execute(
        "SELECT id, product_id, name_jp, name_en, set_name_official FROM products "
        "WHERE category='pokemon_tcg' AND IFNULL(name_jp,'')<>'' AND IFNULL(name_en,'')<>''"
    ).fetchall()
    fix, done = [], 0
    for r in rows:
        g = T.resolve_name_en(r["name_jp"], d1, d2)
        got = g[0] if isinstance(g, tuple) else g
        if got and _norm(got) != _norm(r["name_en"]):
            fix.append((r["id"], r["product_id"], r["name_jp"], r["name_en"], got))
    print(f"=== name_en の取り違え ({'APPLY' if commit else 'DRY-RUN'}) — {len(fix)}行 ===")
    for _, pid, jp, old, new in fix[:12]:
        print(f"    {pid:12s} {jp:14s} {old!r} -> {new!r}")
    if commit:
        for _id, _pid, _jp, _old, new in fix:
            db.execute("UPDATE products SET name_en=?, name_en_source=?, updated_at=? WHERE id=?",
                       (new, "cross_deck_fix_20260904", NOW, _id))
            done += 1
            if done % 20 == 0:          # 途中保存
                db.commit()
        db.commit()
    db.close()
    print("")
    print(f"{'適用' if commit else '(dry-run — --commit で適用)'} {len(fix)} 行")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--commit", action="store_true")
    run(p.parse_args().commit)
