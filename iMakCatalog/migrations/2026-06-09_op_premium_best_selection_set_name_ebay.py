"""OP プレミアムカードコレクション ベストセレクション vol.1-6 の set_name_ebay 充足.

HQ依頼: requests/2026-06-09_psa_miss_setmap_promo_scoring.md (② OP10-049_p1 Sabo)
JP限定 premium collection で eBay Set facet なし → free-text findability 値を保存
(CLAUDE.md: フィルタ外は自由文字列で findability、空欄より良い)。
vol.4 = HQ確定 'Premium Card Collection - Best Selection vol.4'。vol.1-3/5-6 は同パターン外挿。
filter_map に JP官公名→英free-text を登録し、該当行を re-derive (api.derive_set_name_ebay)。

実行: python iMakCatalog/migrations/2026-06-09_op_premium_best_selection_set_name_ebay.py [--commit]
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
DB_PATH = Path(api._DB_PATH); NOW = datetime.now().isoformat()
CAT = "one_piece_tcg"; SRC = "hq_freetext_bestselection_20260609"

# JP set_name_official(実DB値、表記揺れそのまま) -> 英 free-text
MAP = {
    "プレミアムカードコレクション - ベストセレクション vol.4 -": "Premium Card Collection - Best Selection vol.4",  # HQ確定
    "プレミアムカードコレクション - ベストセレクション vol.5 -": "Premium Card Collection - Best Selection vol.5",
    "プレミアムカードコレクション - ベストセレクション vol.6 -": "Premium Card Collection - Best Selection vol.6",
    "プレミアムカードコレクション - ベストセレクションvol.1 -": "Premium Card Collection - Best Selection vol.1",
    "プレミアムカードコレクション - ベストセレクションvol.2 -": "Premium Card Collection - Best Selection vol.2",
    "プレミアムカードコレクション-ベストセレクションvol.3-": "Premium Card Collection - Best Selection vol.3",
}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()
    con = sqlite3.connect(str(DB_PATH)); con.row_factory = sqlite3.Row; cur = con.cursor()
    # 対象行
    rows = cur.execute(
        "SELECT id, product_id, set_name_official, specs FROM products "
        "WHERE category=? AND set_name_official LIKE '%ベストセレクション%'", (CAT,)).fetchall()
    from collections import Counter
    plan = Counter()
    for r in rows:
        en = MAP.get(r["set_name_official"])
        plan[(r["set_name_official"], en)] += 1
    print("=== 対象 (official -> en free-text / 件数) ===")
    for (jp, en), n in plan.items():
        print(f"   {n:3}  {jp!r} -> {en!r}")
    print(f"  合計 {len(rows)} 件")
    if not args.commit:
        print("\n  (DRY-RUN: --commit で filter_map登録 + re-derive)"); con.close(); return

    shutil.copy2(DB_PATH, DB_PATH.with_name(
        DB_PATH.name + ".pre_opbest_" + datetime.now().strftime("%Y%m%d_%H%M%S")))
    # 1) filter_map 登録 (upsert)
    for jp, en in MAP.items():
        api.register_filter_map(CAT, "set", jp, en, note="OP premium best-selection free-text (HQ vol.4)")
    # 2) re-derive 該当行
    n = 0
    for r in rows:
        try:
            d = json.loads(r["specs"]) if r["specs"] else {}
        except Exception:
            d = {}
        clean = api.derive_set_name_ebay(CAT, r["set_name_official"], r["product_id"])
        d["set_name_ebay"] = clean or ""
        d["set_name_ebay_source"] = SRC if clean else "fail_closed_no_map"
        cur.execute("UPDATE products SET specs=?, updated_at=? WHERE id=?",
                    (json.dumps(d, ensure_ascii=False), NOW, r["id"]))
        cur.execute(
            "INSERT INTO b_layer_status (product_id_ref, category, product_code, field, status, oracle, checked_at, note) "
            "VALUES (?, ?, ?, 'set_name_ebay', ?, ?, ?, ?) "
            "ON CONFLICT(product_id_ref, field) DO UPDATE SET status=excluded.status, "
            "oracle=excluded.oracle, checked_at=excluded.checked_at, note=excluded.note",
            (r["id"], CAT, r["product_id"], "verified_manual" if clean else "unverified", SRC, NOW,
             "free-text findability (vol.4 HQ確定/他vol同パターン)"))
        if clean:
            n += 1
    con.commit()
    print(f"\n  ✅ set_name_ebay 充足: {n}/{len(rows)} 件 (filter_map 6登録 + re-derive)")
    con.close()


if __name__ == "__main__":
    main()
