"""Pokemon set_name_ebay 広域cleanup round-3: 残サブ製品の空欄化 (HQ Kind A 原則拡張).

元: requests/2026-06-07_pokemon_broad_cleanup_round2_value_confirm_hq_values.md (Kind A=空set_name→空欄)
round-2 後の監査 [3] 残のうち、set_name(JP)空のサブ製品を HQ承認済 Kind A 原則で空欄化:
  - DPt3 /016 (set_name空, 本体 Beat of the Frontier を借用していた)
  - PBG  /016 (set_name空, 'Promo' 借用)
本体(set_name有)は維持。冪等(既に空欄なら no-op)。

残る [3] = DS(ドラゴンセレクション=要HQ値) / XY(THE BEST OF XY=1セット複数total) /
  SM1p・SM1S・SM1M(異JPセットが同一EN 'Sun & Moon') = 構造的false-positive。別途HQ判断。

実行: python iMakCatalog/migrations/2026-06-07_pokemon_broad_cleanup_round3_blank.py [--commit]
"""
from __future__ import annotations
import argparse, json, shutil, sqlite3, sys
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
BLANK_PREFIX = {"DPt3", "PBG"}  # set_name空 の行のみ対象


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()
    con = sqlite3.connect(str(DB_PATH)); con.row_factory = sqlite3.Row; cur = con.cursor()
    rows = cur.execute("SELECT id,product_id,set_name,specs FROM products WHERE category='pokemon_tcg'").fetchall()
    tgt = []
    for r in rows:
        pre = (r["product_id"] or "").split("-")[0]
        if pre in BLANK_PREFIX and not r["set_name"]:
            d = json.loads(r["specs"]) if r["specs"] else {}
            if d.get("set_name_ebay"):
                tgt.append((r["id"], pre, d))
    print(f"空欄化対象(set_name空サブ製品): {len(tgt)} 件")
    if not args.commit:
        print("(DRY-RUN)"); con.close(); return
    shutil.copy2(DB_PATH, DB_PATH.with_name(DB_PATH.name + ".pre_round3_" + datetime.now().strftime("%Y%m%d_%H%M%S")))
    for _id, pre, d in tgt:
        d.pop("set_name_ebay", None); d["set_name_ebay_source"] = "hq_blank_round3_20260607"
        cur.execute("UPDATE products SET specs=?,updated_at=? WHERE id=?",
                    (json.dumps(d, ensure_ascii=False), datetime.now().isoformat(), _id))
    con.commit(); print(f"投入: {len(tgt)} 件"); con.close()


if __name__ == "__main__":
    main()
