"""b_layer_status name_en 再分類 v2: 種族exact限定 → Tier1-3 rule oracle に拡張.

元: migrations/2026-06-07_b_layer_status_schema.py (v1=pokeapi_direct のみ)
POC: requests/2026-06-07_catalog_q4_name_en_tier23_poc_result.md

scrapers/pokemon_name_translation.translate_by_rule を独立Oracleに使い、name_en を再分類:
  verified_auto : pokeapi_direct/suffix/form で stored と一致 (= pokeapi独立Oracle確認)
  disputed      : rule翻訳と stored が不一致 (match_type 問わず=要確認シグナル)
  unverified    : trainer_* で一致(dict循環の恐れ=独立確認でない) / rule翻訳不能(none=Tier3要)

独立性(B-2): pokeapi系=name_en と独立 → verified_auto 可。trainer dict=生成元と
循環の恐れ → 一致でも unverified に留保(独立Oracle確立まで昇格しない)。

set_name_ebay の status は v1 のまま (本migrationは name_en のみ更新)。

実行: python iMakCatalog/migrations/2026-06-07_b_layer_status_name_en_v2_rule.py [--commit]
"""
from __future__ import annotations
import argparse, re, sqlite3, sys
from collections import Counter
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

DB_PATH = Path(api._DB_PATH)
NOW = datetime.now().isoformat()
_INDEPENDENT = {"pokeapi_direct", "pokeapi_suffix", "pokeapi_form"}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip()).lower()


def classify(name_jp, name_en, poke, api_dict):
    ren, mt = T.translate_by_rule(name_jp, poke, api_dict)
    if mt == "none" or not ren:
        return "unverified", "rule_none", None
    agree = _norm(ren) == _norm(name_en)
    if mt in _INDEPENDENT:
        if agree:
            return "verified_auto", mt, f"rule={ren}"
        return "disputed", mt, f"rule={ren} stored={name_en}"
    # trainer_* (dict循環の恐れ)
    if agree:
        return "unverified", mt + "_dict_agree", None  # 独立確認でないので留保
    return "disputed", mt, f"rule={ren} stored={name_en}"


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()
    poke = T.load_pokeapi_dict(); api_dict = {}
    con = sqlite3.connect(str(DB_PATH)); con.row_factory = sqlite3.Row; cur = con.cursor()
    rows = cur.execute(
        "SELECT id, product_id, name_jp, name_en FROM products WHERE category='pokemon_tcg'"
    ).fetchall()
    recs = []
    for r in rows:
        st, orc, note = classify(r["name_jp"], r["name_en"], poke, api_dict)
        recs.append((r["id"], r["product_id"], st, orc, note))
    print("=== name_en v2 再分類 (status) ===")
    for s, n in Counter(x[2] for x in recs).most_common():
        print(f"   {s:16} {n}")
    print(f"  total: {len(recs)}")
    if not args.commit:
        print("\n  (DRY-RUN)"); con.close(); return
    import shutil
    shutil.copy2(DB_PATH, DB_PATH.with_name(DB_PATH.name + ".pre_blstatus_v2_" + datetime.now().strftime("%Y%m%d_%H%M%S")))
    cur.execute("DELETE FROM b_layer_status WHERE category='pokemon_tcg' AND field='name_en'")
    cur.executemany(
        "INSERT OR REPLACE INTO b_layer_status"
        " (product_id_ref, category, product_code, field, status, oracle, checked_at, note)"
        " VALUES (?,?,?,?,?,?,?,?)",
        [(i, "pokemon_tcg", code, "name_en", st, orc, NOW, note) for (i, code, st, orc, note) in recs],
    )
    con.commit(); print(f"\n  ✅ name_en status 更新: {len(recs)} 行"); con.close()


if __name__ == "__main__":
    main()
