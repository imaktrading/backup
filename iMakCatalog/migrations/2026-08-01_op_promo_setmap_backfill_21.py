"""OP promo set_name_ebay backfill (窓口 GO 2026-08-01, 21件).

依頼: iMak_data/catalog/requests/2026-08-01_set_name_ebay_empty_on_listed_variants_response.md §1
  現行 filter_map で拾える 4 promo set の **空欄行だけ** を Promo Cards で埋める。

★★最重要 (窓口条件3):
  - **set_name_ebay が空欄の行だけ** を埋める。既に値がある行は絶対に触らない。
    (本日 Ultra Prism 誤マップ327件を意図的に空欄化した=commit 6fba129。埋め戻さないこと)
  - 327件は category=pokemon_tcg。本 migration は category=one_piece_tcg のみ → 交差ゼロ。

方式 (Ultra Prism / 4d7772b 同型):
  - scope = 下記 4 promo set_name_official (完全一致) の空欄行のみ。
  - ★dry-run 件数が **21 でなければ abort** (window の ★ gate)。
  - source tag = filter_map_backfill_20260801 / b_layer_status = verified_auto。
  - backup + before-JSON。

※注意: 現行 filter_map は STARTER DECK (ST-31..36) も character-name facet に解決するが、
  それは本 GO の 21件スコープ外 (別 set 種別)。本 migration は 4 promo set に限定し、
  STARTER DECK 85件は「触らない + 別途 window に報告」とする。

実行:
  python migrations/2026-08-01_op_promo_setmap_backfill_21.py           # dry-run
  python migrations/2026-08-01_op_promo_setmap_backfill_21.py --commit  # 適用
"""
from __future__ import annotations
import argparse
import json
import shutil
import sqlite3
import sys
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
SRC_TAG = "filter_map_backfill_20260801"
EXPECTED = 21
BEFORE_JSON = Path("C:/dev/iMak_data/catalog/op_promo_backfill_21_before_20260801.json")

# 窓口 §1 で名指しされた 4 promo set (set_name_official 完全一致)。
# FILM RED は U+2010 (‐) dash + 前後スペース (DB 実文字列を厳密に転記)。
TARGET_OFFICIALS = [
    "プレミアムカードコレクション 25周年エディション",
    "プレミアムカードコレクション ‐ONE PIECE FILM RED ‐",
    "スタンダードバトル 2024年1月優勝記念品",
    "フラッグシップバトル2025 10月ベスト8記念品",
]


def _collect(cur):
    """4 promo set の **set_name_ebay 空欄** 行のみ抽出 (empty-only guard)."""
    targets = []
    ph = ",".join("?" * len(TARGET_OFFICIALS))
    rows = cur.execute(
        f"SELECT id, product_id, set_name_official, specs FROM products "
        f"WHERE category=? AND set_name_official IN ({ph})",
        (CAT, *TARGET_OFFICIALS),
    ).fetchall()
    for r in rows:
        d = json.loads(r["specs"]) if r["specs"] else {}
        cur_val = d.get("set_name_ebay")
        if cur_val:                      # ★既に値あり → 絶対に触らない
            continue
        derived = api.derive_set_name_ebay(CAT, r["set_name_official"], r["product_id"])
        if not derived:                  # 解決不可 → fail-closed 維持 (触らない)
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
    print(f"=== OP promo backfill 21 ({'COMMIT' if args.commit else 'DRY-RUN'}) ===")
    from collections import Counter
    by_set = Counter(t[2] for t in targets)
    for so, n in by_set.most_common():
        print(f"  {n:3d}  {so!r} -> Promo Cards")
    print(f"  >>> 対象 (空欄のみ) = {len(targets)} 件 (期待 {EXPECTED})")

    if len(targets) != EXPECTED:
        print(f"\n  ✗ ABORT: 件数 {len(targets)} != 期待 {EXPECTED}。"
              f"外部書換の疑い。write せず停止 (窓口の ★ gate)。")
        con.close()
        sys.exit(2)

    if not args.commit:
        for _id, pid, so, d, src, dv in sorted(targets, key=lambda t: t[1]):
            print(f"   {pid:14s}: ''({src}) -> {dv!r}")
        print("\n  (DRY-RUN: --commit で適用)")
        con.close()
        return

    backup = DB_PATH.with_name(
        DB_PATH.name + ".pre_op_promo_backfill_21_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
    shutil.copy2(DB_PATH, backup)
    print(f"backup: {backup.name}")

    before = [{"id": t[0], "product_id": t[1], "set_name_official": t[2],
               "set_name_ebay": "", "set_name_ebay_source": t[4]} for t in targets]
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
                (_id, CAT, pid, SRC_TAG, NOW, "OP promo set filter_map backfill 21 (window GO)"))
        except sqlite3.OperationalError:
            pass
        n += 1
        print(f"   {pid:14s}: '' -> {dv!r}")
    con.commit()
    con.close()
    print(f"\n=== done: {n} 行 backfill (source={SRC_TAG}) ===")


if __name__ == "__main__":
    main()
