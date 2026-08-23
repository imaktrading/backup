"""ジニア7行を Jacq に直す + OP01-077_GE の親コピー画像を空に戻す.

依頼:
  requests/2026-08-23_hq_sv1s_097_jacq_not_zinnia.md      (判定①)
  requests/2026-08-23_hq_ge_variant_image_is_parent_copy.md (判定①)

## ★ヒガナ2行は触らない (2026-08-23 実測)

`name_en='Zinnia'` は **9行**あり、7行が「ジニア」、2行が「ヒガナ」。
ヒガナの公式英名は **Zinnia** なので正しい。名前で一括置換すると壊す:

    ジニア  WCS23-024 SVD-129 SV1S-074 SV1S-097 SV1S-104 SVAL-017 SV-P-020  → Jacq
    ヒガナ  SM6a-049 SM6a-059                                              → Zinnia のまま

真因もこれ: `claude_api` がジニアを、同じく英名 Zinnia のヒガナと取り違えている。

## OP01-077_GE

`migrations/2026-08-22_set_name_fill_and_clone_images.py` が clone 行の source_url
(= 親の series ページ) から `product_id` の `_` より前 = OP01-077 の画像を取っていたため、
親と同一URLが入った。公式は GIRLS EDITION の画像を出していないので空が正しい。

実行:
  python migrations/2026-08-23_jacq_rename_and_ge_image_clear.py           # dry-run
  python migrations/2026-08-23_jacq_rename_and_ge_image_clear.py --commit
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
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
JACQ_JP = "ジニア"          # ヒガナ (= 英名 Zinnia が正しい) は対象外
GE_PID = "OP01-077_GE"


def run(commit: bool) -> None:
    db = sqlite3.connect(Path(api._DB_PATH))
    db.row_factory = sqlite3.Row
    mode = "APPLY" if commit else "DRY-RUN"

    print(f"=== 1. ジニア → Jacq ({mode}) ===")
    rows = db.execute(
        "SELECT product_id, name, name_en, specs FROM products "
        "WHERE category='pokemon_tcg' AND name_en='Zinnia'").fetchall()
    n = 0
    for r in rows:
        if r["name"] != JACQ_JP:
            print(f"  - {r['product_id']:12s} {r['name']} は Zinnia が正 → 触らない")
            continue
        s = json.loads(r["specs"] or "{}")
        s["name_en"] = "Jacq" if "name_en" in s else s.get("name_en")
        s.pop("name_en", None)
        s["character_name"] = "Jacq"
        s["name_en_fix"] = "2026-08-23_jacq_not_zinnia"
        print(f"  + {r['product_id']:12s} {r['name']}  Zinnia -> Jacq")
        if commit:
            db.execute(
                "UPDATE products SET name_en=?, name_en_source=?, specs=?, updated_at=? "
                "WHERE category='pokemon_tcg' AND product_id=?",
                ("Jacq", "hq_verified_20260823", json.dumps(s, ensure_ascii=False),
                 NOW, r["product_id"]))
        n += 1
    print(f"  → 対象 {n} 行 / Zinnia のまま {len(rows) - n} 行")

    print(f"\n=== 2. {GE_PID} の画像を空に戻す ({mode}) ===")
    g = db.execute("SELECT product_id, images FROM products "
                   "WHERE category='one_piece_tcg' AND product_id=?", (GE_PID,)).fetchone()
    if g is None:
        print(f"  - {GE_PID} が無い → skip")
    elif (g["images"] or "[]") == "[]":
        print(f"  - {GE_PID} は既に空 → skip")
    else:
        print(f"  + {GE_PID}  {g['images']} -> []  (親 OP01-077 のコピーだった)")
        if commit:
            db.execute("UPDATE products SET images='[]', updated_at=? "
                       "WHERE category='one_piece_tcg' AND product_id=?", (NOW, GE_PID))

    if commit:
        db.commit()
        print("\n✅ 適用")
    else:
        print("\n(dry-run — --commit で適用)")
    db.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--commit", action="store_true")
    run(p.parse_args().commit)
