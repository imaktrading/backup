"""STARTER DECK ST-21 / ST-22 / ST-25 の specs.set_name_ebay を filter_map から再導出.

依頼: iMak_data/catalog/requests/2026-08-01_fix_catalog_data_only_response.md §段階1 (実装GO)

判定 (§0): ① 誤 / ② 正 → ①だけを直す。
    yaml/filter_map (SSOT) は 6/8 に修正済だが、products.specs.set_name_ebay は
    2026-06-08 の stamp が残り、以下 3 セットが古い値のまま:

        ST-21  Ace & Newgate            → Gear 5           (30件)
        ST-22  ONE PIECE FILM RED       → Ace & Newgate    (31件)
        ST-25  Aramaki Premium Card Set → Buggy            (15件)

条件 (§段階1):
  1. backup を取ってから実行 (products.sqlite + 76 件の before JSON)
  2. dry-run で 76 件を出す。76 と一致しなければ write せず質問で止める
  3. 上書きするのは **set_name_official 完全一致 × 現値が上記の誤3値である行** だけ
  4. Ultra Prism 327件・8/1 backfill 21件 が不変であることを実測
  5. source tag = filter_map_restamp_20260801
  6. before/after 件数と、更新後の distinct 値を出力

実行:
  python migrations/2026-08-01_st21_22_25_setname_ebay_restamp.py           # dry-run
  python migrations/2026-08-01_st21_22_25_setname_ebay_restamp.py --commit  # 適用
"""
from __future__ import annotations
import argparse
import json
import shutil
import sqlite3
import sys
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
CAT = "one_piece_tcg"
SRC_TAG = "filter_map_restamp_20260801"
EXPECTED = 76
BEFORE_JSON = Path("C:/dev/iMak_data/catalog/st21_22_25_restamp_before_20260801.json")

# 窓口回答書 §段階1 で名指しされた 3 セット。
# key = set_name_official (完全一致) / value = (現在の誤値, 期待する新値)
TARGETS: list[tuple[str, str, str]] = [
    ("STARTER DECK EX -GEAR5- [ST-21]",       "Ace & Newgate",            "Gear 5"),
    ("STARTER DECK -Ace & Newgate- [ST-22]",  "ONE PIECE FILM RED",       "Ace & Newgate"),
    ("STARTER DECK -BLUE Buggy- [ST-25]",     "Aramaki Premium Card Set", "Buggy"),
]

# 不変であることを実測する invariants (§条件4)
INVARIANT_TAGS = {
    "blanked_by_ultra_prism_mismap_20260731": 327,
    "filter_map_backfill_20260801": 21,
}


def _count_tag(cur, tag: str) -> int:
    return cur.execute(
        "SELECT count(*) FROM products WHERE "
        "json_extract(specs,'$.set_name_ebay_source')=?",
        (tag,),
    ).fetchone()[0]


def _collect(cur):
    """3 セットの **現値が誤3値** の行のみ抽出 (二重条件 guard)."""
    targets = []
    for set_official, wrong_val, expected_new in TARGETS:
        rows = cur.execute(
            "SELECT id, product_id, set_name_official, specs FROM products "
            "WHERE category=? AND set_name_official=?",
            (CAT, set_official),
        ).fetchall()
        for r in rows:
            d = json.loads(r["specs"]) if r["specs"] else {}
            cur_val = d.get("set_name_ebay")
            if cur_val != wrong_val:      # 現値が誤3値でない → 触らない
                continue
            derived = api.derive_set_name_ebay(CAT, r["set_name_official"], r["product_id"])
            if derived != expected_new:   # SSOT の期待値と一致しなければ触らない
                continue
            targets.append({
                "id": r["id"],
                "product_id": r["product_id"],
                "set_name_official": r["set_name_official"],
                "specs_dict": d,
                "before_val": cur_val,
                "before_src": d.get("set_name_ebay_source"),
                "new_val": derived,
            })
    return targets


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()

    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    print(f"=== ST-21/22/25 restamp ({'COMMIT' if args.commit else 'DRY-RUN'}) ===")

    # invariants BEFORE
    inv_before: dict[str, int] = {}
    for tag, expected in INVARIANT_TAGS.items():
        n = _count_tag(cur, tag)
        inv_before[tag] = n
        mark = "OK" if n == expected else "FAIL"
        print(f"  invariant BEFORE: {tag}={n} (expect {expected}) [{mark}]")
        if n != expected:
            print(f"\n  ABORT: invariant baseline {tag} != {expected}")
            con.close()
            sys.exit(3)

    targets = _collect(cur)
    by_set = Counter(t["set_name_official"] for t in targets)
    for so, n in by_set.most_common():
        wrong = next(w for (o, w, _e) in TARGETS if o == so)
        expected = next(e for (o, _w, e) in TARGETS if o == so)
        print(f"  {n:3d}  {so!r}: {wrong!r} -> {expected!r}")
    print(f"  >>> 対象 = {len(targets)} 件 (期待 {EXPECTED})")

    if len(targets) != EXPECTED:
        print(f"\n  ABORT: 件数 {len(targets)} != 期待 {EXPECTED}。write せず停止 (§条件2)。")
        con.close()
        sys.exit(2)

    if not args.commit:
        print("\n  (DRY-RUN: --commit で適用)")
        con.close()
        return

    # backup DB
    backup = DB_PATH.with_name(
        DB_PATH.name + ".pre_st21_22_25_restamp_"
        + datetime.now().strftime("%Y%m%d_%H%M%S"))
    shutil.copy2(DB_PATH, backup)
    print(f"backup: {backup.name}")

    # before JSON
    before = [{
        "id": t["id"],
        "product_id": t["product_id"],
        "set_name_official": t["set_name_official"],
        "set_name_ebay": t["before_val"],
        "set_name_ebay_source": t["before_src"],
    } for t in targets]
    BEFORE_JSON.write_text(
        json.dumps(before, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"before JSON: {BEFORE_JSON} ({len(before)} rows)")

    # apply
    n = 0
    for t in targets:
        d = t["specs_dict"]
        d["set_name_ebay"] = t["new_val"]
        d["set_name_ebay_source"] = SRC_TAG
        cur.execute(
            "UPDATE products SET specs=?, updated_at=? WHERE id=?",
            (json.dumps(d, ensure_ascii=False), NOW, t["id"]),
        )
        try:
            cur.execute(
                "INSERT INTO b_layer_status "
                "(product_id_ref, category, product_code, field, status, "
                " oracle, checked_at, note) "
                "VALUES (?, ?, ?, 'set_name_ebay', 'verified_auto', ?, ?, ?) "
                "ON CONFLICT(product_id_ref, field) DO UPDATE SET "
                "status=excluded.status, oracle=excluded.oracle, "
                "checked_at=excluded.checked_at, note=excluded.note",
                (t["id"], CAT, t["product_id"], SRC_TAG, NOW,
                 "ST-21/22/25 filter_map restamp (window GO)"),
            )
        except sqlite3.OperationalError:
            pass
        n += 1
    con.commit()

    # invariants AFTER
    print("\n=== invariants AFTER ===")
    inv_after: dict[str, int] = {}
    all_ok = True
    for tag, expected in INVARIANT_TAGS.items():
        v = _count_tag(cur, tag)
        inv_after[tag] = v
        mark = "OK" if v == expected else "FAIL"
        if v != expected:
            all_ok = False
        print(f"  {tag}={v} (expect {expected}) [{mark}]")

    # distinct set_name_ebay for the 3 sets AFTER
    print("\n=== distinct set_name_ebay AFTER (3 sets) ===")
    for set_official, _wrong, _expected in TARGETS:
        rows = cur.execute(
            "SELECT specs FROM products WHERE category=? AND set_name_official=?",
            (CAT, set_official),
        ).fetchall()
        vals = Counter()
        for r in rows:
            d = json.loads(r[0]) if r[0] else {}
            vals[d.get("set_name_ebay", "")] += 1
        print(f"  {set_official!r}: {dict(vals)}")

    con.close()
    print(f"\n=== done: {n} 行 restamp (source={SRC_TAG}) ===")
    if not all_ok:
        print("\n  WARNING: invariant が崩れた。要調査。")
        sys.exit(4)


if __name__ == "__main__":
    main()
