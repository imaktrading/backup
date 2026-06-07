"""B層 verified status schema + backfill (HQ B-1 / sequencing step1).

依頼: requests/2026-06-07_catalog_b_layer_audit_poc_response_hq_directive.md (§3 status schema GO)
POC : requests/2026-06-07_catalog_q4_name_en_pokeapi_poc_result.md

`b_layer_status` テーブル新設（4状態: unverified/verified_auto/verified_manual/disputed）。
`_source` 列(出所)とは別軸。backfill:
  - set_name_ebay (pokemon, 直接値architecture):
      source が hq_confirmed*/hq_blank* → verified_manual / それ以外で値あり → unverified
  - name_en (pokemon, 種族完全一致subset, 独立Oracle=pokeapi種族 canonical):
      Oracle一致 → verified_auto / 不一致 → disputed
      (種族非一致・非対象は本backfillでは触らず＝後続POCで Tier2/3 照合)

ゲート強制は本migrationでは行わない(status記録のみ)。is_listable は api.py 側ヘルパー。

実行:
  python iMakCatalog/migrations/2026-06-07_b_layer_status_schema.py          # dry-run(集計のみ)
  python iMakCatalog/migrations/2026-06-07_b_layer_status_schema.py --commit
"""
from __future__ import annotations
import argparse, json, re, shutil, sqlite3, sys
from collections import Counter
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
ORACLE_PATH = Path("C:/dev/iMak_data/catalog/pokemon_translation_cache/ja_en_pokemon_names.json")
_SUF = re.compile(r"\s+(V-UNION|VMAX|VSTAR|GX|EX|ex|V|BREAK|LV\.?X|Prism\s*Star|δ)\b.*$")


def base_en(s: str) -> str:
    return _SUF.sub("", s).strip().rstrip("★◇ δ").strip() if s else ""


DDL = """
CREATE TABLE IF NOT EXISTS b_layer_status (
    product_id_ref INTEGER NOT NULL,
    category       TEXT NOT NULL,
    product_code   TEXT NOT NULL,
    field          TEXT NOT NULL,
    status         TEXT NOT NULL,   -- unverified|verified_auto|verified_manual|disputed
    oracle         TEXT,
    checked_at     TEXT NOT NULL,
    note           TEXT,
    PRIMARY KEY (product_id_ref, field)
);
CREATE INDEX IF NOT EXISTS idx_bls_status ON b_layer_status(field, status);
CREATE INDEX IF NOT EXISTS idx_bls_code   ON b_layer_status(category, product_code);
"""


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()
    oracle = json.load(open(ORACLE_PATH, encoding="utf-8"))

    con = sqlite3.connect(str(DB_PATH)); con.row_factory = sqlite3.Row; cur = con.cursor()
    rows = cur.execute(
        "SELECT id, product_id, name_en, specs FROM products WHERE category='pokemon_tcg'"
    ).fetchall()

    recs = []  # (id, code, field, status, oracle, note)
    for r in rows:
        pid = r["product_id"]; jp = None
        try:
            d = json.loads(r["specs"]) if r["specs"] else {}
        except Exception:
            d = {}
        # --- set_name_ebay (pokemon 直接値) ---
        sne = d.get("set_name_ebay"); src = d.get("set_name_ebay_source") or ""
        if sne:
            if src.startswith("hq_confirmed") or src.startswith("hq_blank"):
                recs.append((r["id"], pid, "set_name_ebay", "verified_manual", src, None))
            else:
                recs.append((r["id"], pid, "set_name_ebay", "unverified", src or "auto", None))
        # --- name_en (種族完全一致subset で Oracle照合) ---
        # name_jp は column。specs に無いので別取得が要る→ ここでは products.name_jp を使う
        # (rows query に name_jp を含めるため下で再取得せず、追加列で取る)
    # name_jp を含めて name_en status を別ループ（上で未取得のため）
    rows2 = cur.execute(
        "SELECT id, product_id, name_jp, name_en FROM products WHERE category='pokemon_tcg'"
    ).fetchall()
    name_en_recs = []
    for r in rows2:
        jp = r["name_jp"]; en = r["name_en"]
        if jp in oracle and base_en(en or ""):
            exp = oracle[jp]
            if base_en(en).lower() == exp.lower():
                name_en_recs.append((r["id"], r["product_id"], "name_en", "verified_auto",
                                     "pokeapi_species", f"oracle={exp}"))
            else:
                name_en_recs.append((r["id"], r["product_id"], "name_en", "disputed",
                                     "pokeapi_species", f"oracle={exp} stored={en}"))
    recs.extend(name_en_recs)

    # サマリ
    by = Counter((f, s) for _, _, f, s, _, _ in recs)
    print("=== backfill 集計 (field, status) ===")
    for (f, s), n in sorted(by.items()):
        print(f"   {f:16} {s:16} {n}")
    print(f"  total rows: {len(recs)}")

    if not args.commit:
        print("\n  (DRY-RUN: テーブル作成/投入なし)")
        con.close(); return

    shutil.copy2(DB_PATH, DB_PATH.with_name(DB_PATH.name + ".pre_blstatus_" + datetime.now().strftime("%Y%m%d_%H%M%S")))
    cur.executescript(DDL)
    cur.execute("DELETE FROM b_layer_status WHERE category='pokemon_tcg'")  # 冪等
    cur.executemany(
        "INSERT OR REPLACE INTO b_layer_status"
        " (product_id_ref, category, product_code, field, status, oracle, checked_at, note)"
        " VALUES (?,?,?,?,?,?,?,?)",
        [(i, "pokemon_tcg", code, f, s, orc, NOW, note) for (i, code, f, s, orc, note) in recs],
    )
    con.commit()
    print(f"\n  ✅ b_layer_status 投入: {len(recs)} 行")
    con.close()


if __name__ == "__main__":
    main()
