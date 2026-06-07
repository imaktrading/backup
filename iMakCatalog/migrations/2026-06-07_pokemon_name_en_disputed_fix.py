"""disputed name_en の根治: rule oracle(name_jp直引き) で正値に補正.

POC: requests/2026-06-07_catalog_q4_name_en_pokeapi_poc_result.md
b_layer_status で disputed の name_en を、translate_by_rule の提案値(name_jp直引き
=番号バグ経路でない canonical)で補正。pokeapi系(direct/suffix/form)のみ対象
(trainer系は別Oracle)。補正後 status を verified_auto に更新。

⚠️ B-2(値は単一源で決めない)厳守のため **HQ greenlight 後に --commit**。
   根拠の2源: pokeapi name_jp直引き + HQ内部多数決(suspect) が共に「現値が誤」と一致。

実行: python iMakCatalog/migrations/2026-06-07_pokemon_name_en_disputed_fix.py [--commit]
"""
from __future__ import annotations
import argparse, re, shutil, sqlite3, sys
from datetime import datetime
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scrapers"))
import api  # noqa: E402
import pokemon_name_translation as T  # noqa: E402
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
DB_PATH = Path(api._DB_PATH); NOW = datetime.now().isoformat()
_INDEP = {"pokeapi_direct", "pokeapi_suffix", "pokeapi_form"}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()
    poke = T.load_pokeapi_dict()
    con = sqlite3.connect(str(DB_PATH)); con.row_factory = sqlite3.Row; cur = con.cursor()
    rows = cur.execute(
        "SELECT b.product_id_ref, b.product_code, p.name_jp, p.name_en "
        "FROM b_layer_status b JOIN products p ON p.id=b.product_id_ref "
        "WHERE b.field='name_en' AND b.status='disputed'"
    ).fetchall()
    fix = []
    skip = []
    for r in rows:
        ren, mt = T.translate_by_rule(r["name_jp"], poke, {})
        if mt in _INDEP and ren:
            fix.append((r["product_id_ref"], r["product_code"], r["name_jp"], r["name_en"], ren))
        else:
            skip.append((r["product_code"], r["name_jp"], mt))
    print(f"disputed {len(rows)} / pokeapi系で補正可 {len(fix)} / 対象外(trainer等) {len(skip)}")
    for i, (rid, code, jp, en, ren) in enumerate(fix):
        if i < 12 or i >= len(fix) - 3:
            print(f"   {code:12} {jp!r:10} {en!r:18} -> {ren!r}")
    if skip:
        print("  対象外:", skip)
    if not args.commit:
        print("\n  (DRY-RUN: HQ greenlight 後に --commit)"); con.close(); return
    shutil.copy2(DB_PATH, DB_PATH.with_name(DB_PATH.name + ".pre_nameenfix_" + datetime.now().strftime("%Y%m%d_%H%M%S")))
    for rid, code, jp, en, ren in fix:
        cur.execute("UPDATE products SET name_en=?, name_en_source=?, updated_at=? WHERE id=?",
                    (ren, "rule_oracle_fix_20260607", NOW, rid))
        cur.execute("UPDATE b_layer_status SET status='verified_auto', oracle='pokeapi+rule_fix', "
                    "checked_at=?, note=? WHERE product_id_ref=? AND field='name_en'",
                    (NOW, f"fixed from {en!r}", rid))
    con.commit(); print(f"\n  ✅ name_en 補正 + verified_auto 昇格: {len(fix)} 件"); con.close()


if __name__ == "__main__":
    main()
