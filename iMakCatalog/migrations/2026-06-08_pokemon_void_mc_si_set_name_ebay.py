"""set_name_ebay 誤ラベル2値 (Movie Commemoration / Special Item) を空欄化 (fail-closed).

HQ回答: requests/2026-06-07_set_name_ebay_unverified_audit_poc_hq_reply_flagged2.md
- MC(766): エリカのラフレシアex 003/742 = 実体「スタートデッキ100 バトルコレクション」。
  "Movie Commemoration" は誤ラベル。eBay Set facet に該当なし。
- SI(293): フシギバナV 001/414 等。"Special Item" は種別語でセット名でない。eBay facet 該当なし。
両者とも確証ある正しい eBay Set 値が無い → 誤ラベルを残すより空欄(可逆)。

処理: specs JSON の set_name_ebay を "" に、source を hq_voided_flagged2 に。
      b_layer_status は **unverified のまま据え置き**(HQ指示=verified昇格しない)。note のみ更新。

実行:
  python iMakCatalog/migrations/2026-06-08_pokemon_void_mc_si_set_name_ebay.py            # dry-run
  python iMakCatalog/migrations/2026-06-08_pokemon_void_mc_si_set_name_ebay.py --commit   # 適用
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
VOID_VALUES = {"Movie Commemoration", "Special Item"}
SRC_TAG = "hq_voided_flagged2_20260608"


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()
    con = sqlite3.connect(str(DB_PATH)); con.row_factory = sqlite3.Row; cur = con.cursor()
    rows = cur.execute(
        "SELECT id, product_id, specs FROM products WHERE category='pokemon_tcg'"
    ).fetchall()

    targets = []  # (id, product_id, old_value, new_specs_json)
    for r in rows:
        try:
            d = json.loads(r["specs"]) if r["specs"] else {}
        except Exception:
            continue
        v = d.get("set_name_ebay")
        if v in VOID_VALUES:
            d["set_name_ebay"] = ""
            d["set_name_ebay_source"] = SRC_TAG
            targets.append((r["id"], r["product_id"], v, json.dumps(d, ensure_ascii=False)))

    by = Counter(t[2] for t in targets)
    print("空欄化対象:", dict(by), "/ 合計", len(targets))
    for code in ("MC-001", "SI-001"):
        s = [t for t in targets if t[1] == code]
        if s:
            print(f"   sample {code}: '{s[0][2]}' -> ''")

    if not args.commit:
        print("\n  (DRY-RUN: --commit で適用)"); con.close(); return

    shutil.copy2(DB_PATH, DB_PATH.with_name(
        DB_PATH.name + ".pre_voidmcsi_" + datetime.now().strftime("%Y%m%d_%H%M%S")))
    for rid, pid, old, newspecs in targets:
        cur.execute("UPDATE products SET specs=?, updated_at=? WHERE id=?", (newspecs, NOW, rid))
        cur.execute(
            "UPDATE b_layer_status SET note=?, checked_at=? "
            "WHERE product_id_ref=? AND field='set_name_ebay'",
            (f"voided from {old!r} (HQ flagged2 fail-closed)", NOW, rid))
    con.commit()
    print(f"\n  ✅ set_name_ebay 空欄化: {len(targets)} 件 (status は unverified 据え置き)")
    con.close()


if __name__ == "__main__":
    main()
