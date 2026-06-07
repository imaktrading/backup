"""Dragonball ebay_filter_map FB04-FB08 誤set名 根治 (出品の正確性).

HQバグ報告: requests/2026-06-08_dragonball_filter_map_fb04_08_wrong_names.md
api.lookup の set_name 導出 = ①set_official完全一致 → ②[CODE]→set_code → ③product_id prefix。
DB表 ebay_filter_map の set_code FB04-08 が誤り(raw=正・filter_map=誤の逆転)で、
live変換経由で約600件が誤set名になっていた。

修正(HQ公式名・複数ソース裏取り済):
  FB04 Fusion Surge        -> Ultra Limit
  FB05 Rising Spark        -> New Adventure
  FB06 Perfect Combination -> Rivals Clash
  FB07 Ultra Limit         -> Wish for Shenron
  FB08 Secret of Evolution -> Saiyan's Pride
さらに `set`(原文一致)表の dead/誤エントリを除去し、実在の英語raw原文→正値を追加。
→ api.lookup が全 FB04-08 行で正値を返すよう根治(product行書換不要・live変換)。

注: FS(スターターデッキ)系は raw とのmismatchあるが HQ正値未提示のため本migでは触らない(別途確認)。

実行: python iMakCatalog/migrations/2026-06-08_dragonball_filter_map_fb04_08_fix.py [--commit]
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

# set_code 訂正 (誤 -> 正)
SET_CODE_FIX = {
    "FB04": "Ultra Limit",
    "FB05": "New Adventure",
    "FB06": "Rivals Clash",
    "FB07": "Wish for Shenron",
    "FB08": "Saiyan's Pride",
}
# `set`(原文一致) の dead/誤エントリ削除 (実在productと不一致のゴミ)
SET_SRC_DELETE = [
    "BOOSTER PACK -FUSION SURGE- [FB04]",
    "BOOSTER PACK -RISING SPARK- [FB05]",
    "BOOSTER PACK -PERFECT COMBINATION- [FB06]",
    "BOOSTER PACK -ULTRA LIMIT- [FB07]",
    "BOOSTER PACK -SECRET OF EVOLUTION- [FB08]",
    "BOOSTER PACK -DESTINED RIVALS- [FB09]",
]
# `set`(原文一致) に実在英語raw原文→正値を追加 (1st-match で確実化)
SET_SRC_ADD = {
    "BOOSTER PACK -ULTRA LIMIT- [FB04]": "Ultra Limit",
    "BOOSTER PACK -NEW ADVENTURE- [FB05]": "New Adventure",
    "BOOSTER PACK -RIVALS CLASH- [FB06]": "Rivals Clash",
    "BOOSTER PACK -WISH FOR SHENRON- [FB07]": "Wish for Shenron",
    "BOOSTER PACK -SAIYAN’S PRIDE- [FB08]": "Saiyan's Pride",  # 生は curly ’
}
SAMPLE_PIDS = ["FB04-001", "FB05-001", "FB06-001", "FB07-001", "FB08-001",
               "FB01-001", "FB09-001", "FB10-001"]


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()
    con = sqlite3.connect(str(DB_PATH)); con.row_factory = sqlite3.Row; cur = con.cursor()

    print("=== 修正前 api.lookup set_name (sample) ===")
    for pid in SAMPLE_PIDS:
        r = api.lookup(category=CAT, product_id=pid)
        print(f"   {pid:10} -> {r['set_name']!r}" if r else f"   {pid:10} -> (None)")

    # 影響件数: set_code FB04-08 にfallbackで効く行数(現lookup値で集計)
    print("\n=== set_code 訂正 ===")
    for code, new in SET_CODE_FIX.items():
        cur_row = cur.execute(
            "SELECT ebay_value FROM ebay_filter_map WHERE category=? AND field='set_code' AND source_value=?",
            (CAT, code)).fetchone()
        old = cur_row["ebay_value"] if cur_row else "(なし)"
        print(f"   {code}: {old!r} -> {new!r}")
    print("\n=== `set` dead削除 ===")
    for s in SET_SRC_DELETE:
        ex = cur.execute("SELECT 1 FROM ebay_filter_map WHERE category=? AND field='set' AND source_value=?",
                         (CAT, s)).fetchone()
        print(f"   {'DEL' if ex else 'skip(無)'}: {s!r}")
    print("\n=== `set` 追加(実在raw) ===")
    for s, v in SET_SRC_ADD.items():
        print(f"   ADD: {s!r} -> {v!r}")

    if not args.commit:
        print("\n  (DRY-RUN: --commit で適用)"); con.close(); return

    shutil.copy2(DB_PATH, DB_PATH.with_name(
        DB_PATH.name + ".pre_dbfmfix_" + datetime.now().strftime("%Y%m%d_%H%M%S")))
    for code, new in SET_CODE_FIX.items():
        cur.execute(
            "UPDATE ebay_filter_map SET ebay_value=? WHERE category=? AND field='set_code' AND source_value=?",
            (new, CAT, code))
    for s in SET_SRC_DELETE:
        cur.execute("DELETE FROM ebay_filter_map WHERE category=? AND field='set' AND source_value=?", (CAT, s))
    _now = datetime.now().isoformat()
    for s, v in SET_SRC_ADD.items():
        cur.execute(
            "INSERT OR REPLACE INTO ebay_filter_map (category, field, source_value, ebay_value, note, created_at) "
            "VALUES (?, 'set', ?, ?, ?, ?)", (CAT, s, v, "hq_fix_fb04_08_20260608", _now))
    con.commit()

    print("\n=== 修正後 api.lookup set_name (sample) ===")
    for pid in SAMPLE_PIDS:
        r = api.lookup(category=CAT, product_id=pid)
        print(f"   {pid:10} -> {r['set_name']!r}" if r else f"   {pid:10} -> (None)")
    print("\n  ✅ ebay_filter_map 訂正完了")
    con.close()


if __name__ == "__main__":
    main()
