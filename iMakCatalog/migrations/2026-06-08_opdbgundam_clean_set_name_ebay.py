"""OP/DB/Gundam: clean set_name_ebay を取り込み時相当で確定保存 + b_layer拡張.

設計依頼: requests/2026-06-08_arch1_store_clean_set_name_ebay_op_db_gundam.md
ユーザー方針(SSOT): 正しい辞書を一度作る→出品は参照のみ。毎回変換しない。

現状: OP/DB の specs.set_name_ebay は raw 文字列("BOOSTER PACK -ROMANCE DAWN- [OP-01]")。
出品が毎回 filter_map で clean化していた=SSOT違反。
本mig: filter_map で **一度だけ** clean化して specs.set_name_ebay に確定保存。
  - 導出 = api._row_to_dict と同順: ①set_official完全一致 → ②[CODE]→set_code → ③product_id prefix
  - 再録(EB02-052_OP15-EB04): set_official が再録先booster → ①で再録先のclean名(=正)
  - filter_map miss → **空欄(fail-closed)**。raw に degrade させない。
+ b_layer_status を OP/DB/Gundam に拡張: clean取得=verified_manual / miss=unverified。
  (OP/DB/Gundam の set名正しさは HQ監査済=filter_mapヒット分は verified_manual)

実行: python iMakCatalog/migrations/2026-06-08_opdbgundam_clean_set_name_ebay.py [--commit]
"""
from __future__ import annotations
import argparse, json, re, shutil, sqlite3, sys
from collections import defaultdict, Counter
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
SRC_TAG = "filter_map_clean_20260608"
CATS = ["one_piece_tcg", "dragonball_scg", "gundam_tcg"]
_CODE_RE = re.compile(r"[\[【]([A-Z][A-Z0-9-]*)[\]】]")


def derive_clean(cat, set_official, product_id):
    """api._row_to_dict と同順で clean eBay facet 値を導出。無ければ None(fail-closed)。"""
    if set_official:
        v = api.to_ebay_value(cat, "set", set_official)
        if v:
            return v
        m = _CODE_RE.search(set_official)
        if m:
            v = api.to_ebay_value(cat, "set_code", m.group(1))
            if v:
                return v
    if product_id and "-" in product_id:
        pref = product_id.split("-", 1)[0]
        for cand in {pref, pref.upper(), pref.lower()}:
            v = api.to_ebay_value(cat, "set_code", cand)
            if v:
                return v
    return None


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()
    con = sqlite3.connect(str(DB_PATH)); con.row_factory = sqlite3.Row; cur = con.cursor()

    updates = []      # (id, new_specs_json, clean_or_blank, status)
    summary = {}
    for cat in CATS:
        rows = cur.execute(
            "SELECT id, product_id, set_name_official, specs FROM products WHERE category=?", (cat,)).fetchall()
        clean_n = blank_n = 0
        by_code = defaultdict(set)
        for r in rows:
            try:
                d = json.loads(r["specs"]) if r["specs"] else {}
            except Exception:
                d = {}
            clean = derive_clean(cat, r["set_name_official"], r["product_id"])
            d["set_name_ebay"] = clean or ""
            d["set_name_ebay_source"] = SRC_TAG if clean else "fail_closed_no_map"
            status = "verified_manual" if clean else "unverified"
            updates.append((r["id"], cat, r["product_id"], json.dumps(d, ensure_ascii=False), status))
            if clean:
                clean_n += 1
                m = re.match(r"^([A-Za-z0-9]+)[-_]", r["product_id"])
                by_code[m.group(1) if m else r["product_id"]].add(clean)
            else:
                blank_n += 1
        split = {k: v for k, v in by_code.items() if len(v) > 1}
        summary[cat] = (len(rows), clean_n, blank_n, split)

    print("=== 導出サマリ ===")
    for cat, (tot, cn, bn, split) in summary.items():
        print(f"  {cat}: total={tot} clean={cn} blank(fail-closed)={bn}")
        if split:
            print(f"     ⚠️ set_code割れ(複数clean値, 再録/multi-deck以外なら要確認): {len(split)}")
            for k, vs in list(split.items())[:8]:
                print(f"        {k}: {sorted(vs)}")

    if not args.commit:
        print(f"\n  更新対象 {len(updates)} 件 (DRY-RUN: --commit で適用)"); con.close(); return

    shutil.copy2(DB_PATH, DB_PATH.with_name(
        DB_PATH.name + ".pre_opdbgclean_" + datetime.now().strftime("%Y%m%d_%H%M%S")))
    for pid_ref, cat, code, newspecs, status in updates:
        cur.execute("UPDATE products SET specs=?, updated_at=? WHERE id=?", (newspecs, NOW, pid_ref))
        cur.execute(
            "INSERT INTO b_layer_status (product_id_ref, category, product_code, field, status, oracle, checked_at, note) "
            "VALUES (?, ?, ?, 'set_name_ebay', ?, ?, ?, ?) "
            "ON CONFLICT(product_id_ref, field) DO UPDATE SET status=excluded.status, "
            "oracle=excluded.oracle, checked_at=excluded.checked_at, note=excluded.note",
            (pid_ref, cat, code, status, SRC_TAG, NOW, "opdbgundam clean re-derive"))
    con.commit()
    print(f"\n  ✅ clean set_name_ebay 保存 + b_layer拡張: {len(updates)} 件"); con.close()


if __name__ == "__main__":
    main()
