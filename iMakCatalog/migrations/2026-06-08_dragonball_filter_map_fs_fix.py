"""Dragonball ebay_filter_map FS(スターターデッキ) set_code 誤名 根治.

HQ回答: requests/2026-06-08_dragonball_fs_starter_deck_names_and_loader.md
FBと同型(yaml正/DB表stale)。map のテーマ名(Saiyan Genesis/Pirates 等)は誤、
公式英語名=rawキャラ名(Son Goku/Bardock 等)。DB表 set_code を yaml正値に同期。
dead な `set`(原文一致) テーマ名エントリ(実在productと不一致)も削除。
FS04/FS09-12 は既に正。

実行: python iMakCatalog/migrations/2026-06-08_dragonball_filter_map_fs_fix.py [--commit]
"""
from __future__ import annotations
import argparse, shutil, sqlite3, sys
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
CAT = "dragonball_scg"

SET_CODE_FIX = {
    "FS01": "Starter Deck Son Goku",
    "FS02": "Starter Deck Vegeta",
    "FS03": "Starter Deck Broly",
    "FS05": "Starter Deck Bardock",
    "FS06": "Starter Deck Son Goku (Mini)",
    "FS07": "Starter Deck Vegeta (Mini)",
    "FS08": "Starter Deck Vegeta (Mini) Super Saiyan 3",
}
SET_SRC_DELETE = [  # 実在raw(キャラ名)と不一致のテーマ名 dead エントリ
    "STARTER DECK SAIYAN GENESIS [FS01]",
    "STARTER DECK BUDOKAI WARRIORS [FS02]",
    "STARTER DECK PERFECTION [FS03]",
    "STARTER DECK ANDROIDS [FS05]",
    "STARTER DECK PIRATES [FS06]",
    "STARTER DECK ULTIMATE WARRIORS [FS07]",
    "STARTER DECK MAJIN BUU [FS08]",
]
SAMPLE = ["FS01-001", "FS02-001", "FS03-001", "FS04-001", "FS05-001",
          "FS06-001", "FS07-001", "FS08-001", "FS09-001"]


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()
    con = sqlite3.connect(str(DB_PATH)); con.row_factory = sqlite3.Row; cur = con.cursor()

    print("=== 修正前 api.lookup set_name (sample) ===")
    for pid in SAMPLE:
        r = api.lookup(category=CAT, product_id=pid)
        print(f"   {pid:10} -> {r['set_name']!r}" if r else f"   {pid:10} -> None")
    print("\n=== set_code 訂正 ===")
    for code, new in SET_CODE_FIX.items():
        old = cur.execute("SELECT ebay_value FROM ebay_filter_map WHERE category=? AND field='set_code' AND source_value=?",
                          (CAT, code)).fetchone()
        print(f"   {code}: {(old['ebay_value'] if old else '(なし)')!r} -> {new!r}")
    print("\n=== dead `set` 削除 ===")
    for s in SET_SRC_DELETE:
        ex = cur.execute("SELECT 1 FROM ebay_filter_map WHERE category=? AND field='set' AND source_value=?",
                         (CAT, s)).fetchone()
        print(f"   {'DEL' if ex else 'skip'}: {s!r}")

    if not args.commit:
        print("\n  (DRY-RUN: --commit で適用)"); con.close(); return

    shutil.copy2(DB_PATH, DB_PATH.with_name(
        DB_PATH.name + ".pre_fsfix_" + datetime.now().strftime("%Y%m%d_%H%M%S")))
    for code, new in SET_CODE_FIX.items():
        cur.execute("UPDATE ebay_filter_map SET ebay_value=? WHERE category=? AND field='set_code' AND source_value=?",
                    (new, CAT, code))
    for s in SET_SRC_DELETE:
        cur.execute("DELETE FROM ebay_filter_map WHERE category=? AND field='set' AND source_value=?", (CAT, s))
    con.commit()
    print("\n=== 修正後 api.lookup set_name (sample) ===")
    for pid in SAMPLE:
        r = api.lookup(category=CAT, product_id=pid)
        print(f"   {pid:10} -> {r['set_name']!r}" if r else f"   {pid:10} -> None")
    print("\n  ✅ FS set_code 訂正完了")
    con.close()


if __name__ == "__main__":
    main()
