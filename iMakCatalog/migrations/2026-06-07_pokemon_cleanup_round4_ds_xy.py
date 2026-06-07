"""広域cleanup round-4 (HQ確定 2026-06-07): DS/XY 値 + XY total データ誤り是正.

元: requests/2026-06-07_pokemon_broad_cleanup_round2_value_confirm_hq_values_processed_hq_reply.md

(a) 値誤り → 正値:
    DS (ドラゴンセレクション) set_name_ebay: Stellar Crown(誤) → Dragon Vault (英語版"Dragon Vault")
    XY (THE BEST OF XY)     set_name_ebay: XY—Evolutions(誤) → The Best of XY
(b) XY card_number_total データ誤り: THE BEST OF XY は171枚1セットなのに一部が
    total=048/041 (scrape誤) → 171 に是正 (42件)。是正で [3] の The Best of XY が単一total化。

残[3]: Sun & Moon=HQ audit whitelist / cardID=HQ skip (Catalog対応不要)。

実行: python iMakCatalog/migrations/2026-06-07_pokemon_cleanup_round4_ds_xy.py [--commit]
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
DB_PATH = Path(api._DB_PATH); NOW = datetime.now().isoformat()
XY_SET_JP = "ハイクラスパック「THE BEST OF XY」"
BAD_TOTAL = {"048", "041"}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()
    con = sqlite3.connect(str(DB_PATH)); con.row_factory = sqlite3.Row; cur = con.cursor()
    rows = cur.execute(
        "SELECT id, product_id, set_name, specs FROM products WHERE category='pokemon_tcg' "
        "AND (product_id LIKE 'DS-%' OR product_id LIKE 'XY-%')"
    ).fetchall()
    val_upd = []   # set_name_ebay 値修正
    tot_upd = []   # card_number_total 是正
    for r in rows:
        pre = r["product_id"].split("-")[0]
        try:
            d = json.loads(r["specs"]) if r["specs"] else {}
        except Exception:
            d = {}
        new = None
        if pre == "DS":
            new = "Dragon Vault"
        elif pre == "XY" and r["set_name"] == XY_SET_JP:
            new = "The Best of XY"
        if new and d.get("set_name_ebay") != new:
            val_upd.append((r["id"], r["product_id"], d.get("set_name_ebay"), new, d))
        # total 是正 (XY-prefix のみ)
        if pre == "XY" and d.get("card_number_total") in BAD_TOTAL:
            tot_upd.append((r["id"], r["product_id"], d.get("card_number_total"), d))

    print(f"set_name_ebay 値修正: {len(val_upd)} 件 (DS={sum(1 for x in val_upd if x[1].startswith('DS'))}/XY={sum(1 for x in val_upd if x[1].startswith('XY'))})")
    print(f"card_number_total 是正(→171): {len(tot_upd)} 件")
    for _id, pid, bef, aft, _ in val_upd[:4]:
        print(f"   val {pid}: {bef!r} -> {aft!r}")
    print(f"   total 例: {[x[1] for x in tot_upd[:5]]}")

    if not args.commit:
        print("\n  (DRY-RUN)"); con.close(); return
    shutil.copy2(DB_PATH, DB_PATH.with_name(DB_PATH.name + ".pre_round4_" + datetime.now().strftime("%Y%m%d_%H%M%S")))
    for _id, pid, bef, aft, d in val_upd:
        d["set_name_ebay"] = aft; d["set_name_ebay_source"] = "hq_confirmed_round4_20260607"
        cur.execute("UPDATE products SET specs=?,updated_at=? WHERE id=?", (json.dumps(d, ensure_ascii=False), NOW, _id))
    # total 是正は specs を最新で再取得 (val_upd と id 重複しうるため再読込)
    for _id, pid, bad, _ in tot_upd:
        row = cur.execute("SELECT specs FROM products WHERE id=?", (_id,)).fetchone()
        d = json.loads(row["specs"]) if row["specs"] else {}
        d["card_number_total"] = "171"; d["card_number_total_source"] = "hq_fix_round4_20260607"
        cur.execute("UPDATE products SET specs=?,updated_at=? WHERE id=?", (json.dumps(d, ensure_ascii=False), NOW, _id))
    con.commit(); print(f"\n  ✅ 値修正 {len(val_upd)} + total是正 {len(tot_upd)}"); con.close()


if __name__ == "__main__":
    main()
