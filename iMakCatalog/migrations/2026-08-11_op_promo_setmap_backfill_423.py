"""OP promo/event set_name_ebay backfill 423 行 (窓口 GO 2026-08-11).

依頼: iMak_data/catalog/requests/2026-08-11_op03_001_p2_set_name_ebay_empty_response.md
  段1 (yaml 118件追加) 完了後、fail_closed_no_map で空欄化されていた 423行を
  api.derive_set_name_ebay() の再走で埋める。

★★最重要 (empty-only guard):
  - **set_name_ebay が空欄の行だけ** を埋める。既に値がある行は絶対に触らない。
  - dry-run 件数が **423 でなければ abort** (窓口 §検収条件)。
  - 内訳: Group A 85 (ST-31..36 + 既存 promo/event 系, yaml 追加前から埋まる筈のもの)
        + Group B 338 (段1 で 118 distinct source_value を Promo Cards に足した分)

方式 (op_promo_setmap_backfill_21 と同型):
  - scope = category=one_piece_tcg かつ specs.set_name_ebay=''
  - derive_set_name_ebay() が None を返す行は据え置き (fail-closed 維持)
  - source tag = filter_map_backfill_20260811_op_promo_423
  - b_layer_status を verified_auto に stamp (blanking からの回復)
  - backup + before-JSON

実行:
  python migrations/2026-08-11_op_promo_setmap_backfill_423.py           # dry-run
  python migrations/2026-08-11_op_promo_setmap_backfill_423.py --commit  # 適用
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
SRC_TAG = "filter_map_backfill_20260811_op_promo_423"
EXPECTED = 423
BEFORE_JSON = Path("C:/dev/iMak_data/catalog/op_promo_backfill_423_before_20260811.json")


def _collect(cur):
    """category one_piece_tcg の specs.set_name_ebay='' 行を全部拾い、
    derive_set_name_ebay() で埋まるもののみ target 化 (empty-only guard)."""
    targets = []
    rows = cur.execute(
        "SELECT id, product_id, set_name_official, specs FROM products WHERE category=?",
        (CAT,),
    ).fetchall()
    for r in rows:
        d = json.loads(r["specs"]) if r["specs"] else {}
        cur_val = d.get("set_name_ebay")
        if cur_val:  # ★既に値あり → 絶対に触らない
            continue
        derived = api.derive_set_name_ebay(CAT, r["set_name_official"], r["product_id"])
        if not derived:  # 解決不可 → fail-closed 維持 (触らない)
            continue
        targets.append((r["id"], r["product_id"], r["set_name_official"],
                        d, d.get("set_name_ebay_source"), derived))
    return targets


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()

    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    targets = _collect(cur)
    print(f"=== OP promo backfill 423 ({'COMMIT' if args.commit else 'DRY-RUN'}) ===")
    by_ebay = Counter(t[5] for t in targets)
    for ev, n in by_ebay.most_common():
        print(f"  {n:4d}  -> {ev!r}")
    print(f"  >>> 対象 (空欄のみ) = {len(targets)} 件 (期待 {EXPECTED})")

    if len(targets) != EXPECTED:
        print(f"\n  ✗ ABORT: 件数 {len(targets)} != 期待 {EXPECTED}。"
              f"yaml 変更 or 外部書換の疑い。write せず停止 (窓口の ★ gate)。")
        con.close()
        sys.exit(2)

    if not args.commit:
        # dry-run: top 10 変換の内訳を出す
        by_set = Counter((t[2], t[5]) for t in targets)
        print("\n  内訳 (set_name_official -> ebay, 上位 15):")
        for (so, ev), n in by_set.most_common(15):
            print(f"    {n:4d}  {so!r} -> {ev!r}")
        print("\n  (DRY-RUN: --commit で適用)")
        con.close()
        return

    backup = DB_PATH.with_name(
        DB_PATH.name + ".pre_op_promo_backfill_423_"
        + datetime.now().strftime("%Y%m%d_%H%M%S"))
    shutil.copy2(DB_PATH, backup)
    print(f"backup: {backup.name}")

    before = [{"id": t[0], "product_id": t[1], "set_name_official": t[2],
               "set_name_ebay": "", "set_name_ebay_source": t[4],
               "derived": t[5]} for t in targets]
    BEFORE_JSON.write_text(json.dumps(before, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"before JSON: {BEFORE_JSON} ({len(before)} rows)")

    n = 0
    for _id, pid, so, d, src, dv in targets:
        d["set_name_ebay"] = dv
        d["set_name_ebay_source"] = SRC_TAG
        cur.execute("UPDATE products SET specs=?, updated_at=? WHERE id=?",
                    (json.dumps(d, ensure_ascii=False), NOW, _id))
        try:
            cur.execute(
                "INSERT INTO b_layer_status "
                "(product_id_ref, category, product_code, field, status, oracle, checked_at, note) "
                "VALUES (?, ?, ?, 'set_name_ebay', 'verified_auto', ?, ?, ?) "
                "ON CONFLICT(product_id_ref, field) DO UPDATE SET "
                "status=excluded.status, oracle=excluded.oracle, "
                "checked_at=excluded.checked_at, note=excluded.note",
                (_id, CAT, pid, SRC_TAG, NOW,
                 "OP promo/event filter_map backfill 423 (window GO 2026-08-11)"))
        except sqlite3.OperationalError:
            pass
        n += 1
    con.commit()
    con.close()
    print(f"\n=== done: {n} 行 backfill (source={SRC_TAG}) ===")


if __name__ == "__main__":
    main()
