"""set_name_ebay literal twin 残 (XY11/BW8/BW3) を確定em-dash値に訂正.

HQ依頼: requests/2026-06-08_set_name_ebay_literal_residual_xy11_bw8_bw3.md
JP twin セットの直訳(Fever-Burst Fighter 等)が set_name_ebay に残存(eBay facet外)。
b_layer round1-6 は unverified 75値駆動だったため、既 verified_manual だった
これら(別経路)を取りこぼしていた。確定値(em-dash)に訂正(status は verified_manual 維持)。

twin signature = 1 set_code に literal 2値。本対象は監査(set_code割れ)で確定の3 set_code:
  XY11 (爆熱の闘士+冷酷の反逆者)  -> XY—Steam Siege
  BW8  (ラセンフォース+サンダーナックル) -> Black & White—Plasma Freeze
  BW3  (サイコドライブ+ヘイルブリザード) -> Black & White—Next Destinies

実行: python iMakCatalog/migrations/2026-06-08_pokemon_set_name_ebay_literal_twin_fix.py [--commit]
"""
from __future__ import annotations
import argparse, json, shutil, sqlite3, sys
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
SRC_TAG = "hq_confirmed_twinfix_20260608"
# product_id set_code prefix -> 確定 em-dash 値
FIX = {
    "XY11": "XY—Steam Siege",
    "BW8": "Black & White—Plasma Freeze",
    "BW3": "Black & White—Next Destinies",
}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()
    con = sqlite3.connect(str(DB_PATH)); con.row_factory = sqlite3.Row; cur = con.cursor()
    apply = []
    for code, new in FIX.items():
        rows = cur.execute(
            "SELECT b.product_id_ref, p.specs FROM b_layer_status b "
            "JOIN products p ON p.id=b.product_id_ref "
            "WHERE b.field='set_name_ebay' AND (p.product_id LIKE ? OR p.product_id LIKE ?)",
            (code + "-%", code + "_%")).fetchall()
        before = Counter()
        for r in rows:
            try:
                d = json.loads(r["specs"]) if r["specs"] else {}
            except Exception:
                d = {}
            old = d.get("set_name_ebay")
            before[old] += 1
            d["set_name_ebay"] = new
            d["set_name_ebay_source"] = SRC_TAG
            apply.append((r["product_id_ref"], json.dumps(d, ensure_ascii=False)))
        print(f"   {code} -> {new!r}  (現値: {dict(before)})")
    print(f"\n  訂正対象: {len(apply)} 件")

    if not args.commit:
        print("\n  (DRY-RUN: --commit で適用)"); con.close(); return

    shutil.copy2(DB_PATH, DB_PATH.with_name(
        DB_PATH.name + ".pre_twinfix_" + datetime.now().strftime("%Y%m%d_%H%M%S")))
    for rid, newspecs in apply:
        cur.execute("UPDATE products SET specs=?, updated_at=? WHERE id=?", (newspecs, NOW, rid))
        cur.execute("UPDATE b_layer_status SET oracle=?, checked_at=?, note=? "
                    "WHERE product_id_ref=? AND field='set_name_ebay'",
                    (SRC_TAG, NOW, "twin literal -> em-dash", rid))
    con.commit()
    print(f"\n  ✅ set_name_ebay twin literal 訂正: {len(apply)} 件 (verified_manual維持)")
    con.close()


if __name__ == "__main__":
    main()
