"""Ultra Prism 誤マップ 327件の set_name_ebay 空欄化 (N:1 backfill 是正) — 2026-07-31 起草 / 2026-08-01 実施

依頼: requests/2026-07-31_audit_catalog_fix_tcg_draft_promoted_response.md (窓口 GO) +
      2026-07-31_pokemon_ultra_prism_mismap_327 (合体)。

問題: hq_confirmed_facet_20260608 由来の backfill が、**4つの別 JP セット**を全て
  eBay facet 'Sun & Moon—Ultra Prism' に **N:1 で誤マップ**していた:
    ハイクラスパック「GXバトルブースト」 121
    拡張パック「ウルトラサン」           82
    拡張パック「ウルトラムーン」          69
    拡張パック「ウルトラフォース」        55
    = 327
是正: **公式に無いものを推測で埋めない (空欄が正)**。327行の specs.set_name_ebay を空欄化
  (json_remove) + set_name_ebay_source を blank マーカーに + b_layer_status を unverified に。

安全条件 (窓口):
  - 事前 backup 必須 (products.sqlite.bak_20260801_pre_ultra_prism_revert)。
  - **実行時に再度 327 を照合。不一致なら write せず abort** (7/31 以降の別経路書換の検出)。
  - before/after 件数を報告。

実行: python migrations/2026-07-31_revert_ultra_prism_mismap.py        (dry-run: 照合のみ)
      python migrations/2026-07-31_revert_ultra_prism_mismap.py --apply
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

DB = "C:/dev/iMak_data/catalog/products.sqlite"
BEFORE_JSON = Path("C:/dev/iMak_data/catalog/products_ultra_prism_before_20260801.json")

MISMAPPED_EBAY = "Sun & Moon—Ultra Prism"
EXPECTED_TOTAL = 327
EXPECTED_SETS = {
    "ハイクラスパック「GXバトルブースト」": 121,
    "拡張パック「ウルトラサン」": 82,
    "拡張パック「ウルトラムーン」": 69,
    "拡張パック「ウルトラフォース」": 55,
}
BLANK_SOURCE = "blanked_by_ultra_prism_mismap_20260731"
BLANK_NOTE = "reverted from Sun & Moon—Ultra Prism (mismapped)"


def _target_rows(conn):
    return conn.execute(
        "select id, product_id, set_name_official, specs from products "
        "where category='pokemon_tcg' "
        "and json_extract(specs,'$.set_name_ebay')=?",
        (MISMAPPED_EBAY,),
    ).fetchall()


def main(apply: bool) -> None:
    conn = sqlite3.connect(DB)
    rows = _target_rows(conn)
    total = len(rows)
    by_set: dict[str, int] = {}
    for _id, _pid, so, _sp in rows:
        by_set[so] = by_set.get(so, 0) + 1

    print(f"=== Ultra Prism mismap revert ({'APPLY' if apply else 'DRY-RUN'}) ===")
    print(f"before: {total} rows with set_name_ebay={MISMAPPED_EBAY!r}")
    for so, n in sorted(by_set.items(), key=lambda x: -x[1]):
        print(f"  {so!r}: {n}")

    # ★安全ガード: 期待 327 / 4 セット と完全一致しなければ abort (推測で上書きしない)
    if total != EXPECTED_TOTAL or by_set != EXPECTED_SETS:
        print(f"\n⛔ ABORT: 実測 ({total}, {len(by_set)}セット) が期待 (327, 4セット) と不一致。")
        print("   7/31 以降に別経路で書き換わった可能性。原因不明のまま上書きしない (質問で止める)。")
        sys.exit(2)
    print("\n✅ 照合一致 (327 / 4セット exhaustive)。")

    if not apply:
        print("dry-run: write せず終了 (--apply で実行)。")
        return

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    # before JSON (証跡)
    before = []
    for rid, pid, so, sp in rows:
        d = json.loads(sp)
        bl = conn.execute(
            "select status, oracle, note, checked_at from b_layer_status "
            "where product_id_ref=? and field='set_name_ebay'", (rid,)
        ).fetchone()
        before.append({
            "id": rid, "product_id": pid, "set_name_official": so,
            "set_name_ebay": d.get("set_name_ebay"),
            "set_name_ebay_source": d.get("set_name_ebay_source"),
            "b_layer_status": ({"status": bl[0], "oracle": bl[1], "note": bl[2],
                                "checked_at": bl[3]} if bl else None),
        })
    BEFORE_JSON.write_text(json.dumps(before, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"before JSON 保存: {BEFORE_JSON} ({len(before)} rows)")

    # write
    n_specs = n_bl = 0
    for rid, pid, so, sp in rows:
        d = json.loads(sp)
        d.pop("set_name_ebay", None)                     # json_remove
        d["set_name_ebay_source"] = BLANK_SOURCE
        conn.execute("update products set specs=?, updated_at=? where id=?",
                     (json.dumps(d, ensure_ascii=False), now, rid))
        n_specs += 1
        cur = conn.execute(
            "update b_layer_status set status='unverified', oracle=?, note=?, checked_at=? "
            "where product_id_ref=? and field='set_name_ebay'",
            (BLANK_SOURCE, BLANK_NOTE, now, rid))
        n_bl += cur.rowcount
    conn.commit()

    after = len(_target_rows(conn))
    print(f"specs 更新: {n_specs} / b_layer_status 更新: {n_bl}")
    print(f"after: {after} rows with set_name_ebay={MISMAPPED_EBAY!r} (期待 0)")


if __name__ == "__main__":
    main(apply="--apply" in sys.argv)
