"""name_en disputed 残3件(trainer) を HQ確定値で補正 → verified_manual昇格 (disputed 3→0).

HQ依頼: requests/2026-06-08_name_en_disputed_3_trainers_final_fix.md
pokeapi対象外でdisputed据置だった trainer 3件。源1=name_jp直引き(キャラ英語公式名)
源2=現値が明らかに誤/空。human確定値のため verified_manual。

実行: python iMakCatalog/migrations/2026-06-08_pokemon_name_en_disputed_trainers_fix.py [--commit]
"""
from __future__ import annotations
import argparse, shutil, sqlite3, sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import api  # noqa: E402
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
DB_PATH = Path(api._DB_PATH)
NOW = datetime.now().isoformat()
SRC_TAG = "hq_confirmed_trainer_20260608"
# product_code -> 確定 name_en
FIX = {"SA-021": "Bede", "XY-036": "N", "362/SM-P": "Erika"}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()
    con = sqlite3.connect(str(DB_PATH)); con.row_factory = sqlite3.Row; cur = con.cursor()
    targets = []
    for code, new in FIX.items():
        r = cur.execute(
            "SELECT b.product_id_ref, p.name_jp, p.name_en, b.status FROM b_layer_status b "
            "JOIN products p ON p.id=b.product_id_ref "
            "WHERE b.field='name_en' AND b.product_code=?", (code,)).fetchone()
        if not r:
            print(f"   ⚠️ {code}: b_layer_status 行なし(skip)"); continue
        print(f"   {code:12} {r['name_jp']!r:10} {r['name_en']!r} [{r['status']}] -> {new!r}")
        targets.append((r["product_id_ref"], r["name_en"], new))

    if not args.commit:
        print(f"\n  対象 {len(targets)} 件 (DRY-RUN: --commit で適用)"); con.close(); return

    shutil.copy2(DB_PATH, DB_PATH.with_name(
        DB_PATH.name + ".pre_trainerfix_" + datetime.now().strftime("%Y%m%d_%H%M%S")))
    for rid, old, new in targets:
        cur.execute("UPDATE products SET name_en=?, name_en_source=?, updated_at=? WHERE id=?",
                    (new, SRC_TAG, NOW, rid))
        cur.execute("UPDATE b_layer_status SET status='verified_manual', oracle=?, checked_at=?, "
                    "note=? WHERE product_id_ref=? AND field='name_en'",
                    (SRC_TAG, NOW, f"trainer fixed from {old!r}", rid))
    con.commit()
    n = cur.execute("SELECT COUNT(*) FROM b_layer_status WHERE field='name_en' AND status='disputed'").fetchone()[0]
    print(f"\n  ✅ 補正+verified_manual昇格: {len(targets)} 件 / 残 disputed = {n}")
    con.close()


if __name__ == "__main__":
    main()
