"""set_name_ebay unverified → verified_manual 昇格 (HQ承認値リスト駆動).

POC/監査: requests/2026-06-07_set_name_ebay_unverified_audit_poc.md
unverified 11,421件(75 distinct値) のうち、HQ が eBay "Set" フィルタと突合して
承認した値だけを verified_manual に昇格する。

⚠️ B-2(値は単一源で決めない)厳守: 昇格は **HQ承認リスト(--approved)必須**。
   承認リストに無い値は unverified のまま据え置き(fail-closed)。

承認リスト形式: 1行1値の UTF-8 テキスト (# と空行は無視)。
  Sun & Moon—Lost Thunder
  Scarlet & Violet—Paldean Fates
  ...

実行:
  # dry-run (承認リストの突合結果のみ表示, DB無変更)
  python iMakCatalog/migrations/2026-06-07_pokemon_set_name_ebay_promote.py --approved approved.txt
  # 適用
  python iMakCatalog/migrations/2026-06-07_pokemon_set_name_ebay_promote.py --approved approved.txt --commit
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
SRC_TAG = "hq_confirmed_setlist_20260607"


def load_approved(path: Path) -> set[str]:
    vals = set()
    for ln in path.read_text(encoding="utf-8").splitlines():
        s = ln.strip()
        if s and not s.startswith("#"):
            vals.add(s)
    return vals


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--approved", required=True, help="HQ承認値リスト(1行1値)")
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()

    approved = load_approved(Path(args.approved))
    print(f"承認値リスト: {len(approved)} 値")

    con = sqlite3.connect(str(DB_PATH)); con.row_factory = sqlite3.Row; cur = con.cursor()
    rows = cur.execute(
        "SELECT b.product_id_ref, p.specs FROM b_layer_status b "
        "JOIN products p ON p.id=b.product_id_ref "
        "WHERE b.field='set_name_ebay' AND b.status='unverified'"
    ).fetchall()

    hit, miss = [], Counter()
    for r in rows:
        try:
            d = json.loads(r["specs"]) if r["specs"] else {}
        except Exception:
            d = {}
        v = d.get("set_name_ebay")
        if v in approved:
            hit.append((r["product_id_ref"], v))
        else:
            miss[v] += 1

    print(f"昇格対象(承認値と一致): {len(hit)} 件")
    print(f"据え置き(未承認のまま unverified): {sum(miss.values())} 件 / {len(miss)} 値")
    # 承認リストにあるが DB に1件も無い値 (typo検出)
    db_vals = {v for _, v in hit}
    unused = approved - db_vals
    if unused:
        print(f"  ⚠️ 承認リストにあるが DB未ヒットの値 {len(unused)} (typo疑い): {sorted(unused)}")

    if not args.commit:
        print("\n  (DRY-RUN: --commit で昇格適用)"); con.close(); return

    shutil.copy2(DB_PATH, DB_PATH.with_name(
        DB_PATH.name + ".pre_snepromote_" + datetime.now().strftime("%Y%m%d_%H%M%S")))
    for rid, v in hit:
        cur.execute(
            "UPDATE b_layer_status SET status='verified_manual', oracle=?, checked_at=?, "
            "note=? WHERE product_id_ref=? AND field='set_name_ebay'",
            (SRC_TAG, NOW, f"hq_approved {v!r}", rid))
    con.commit()
    print(f"\n  ✅ verified_manual 昇格: {len(hit)} 件"); con.close()


if __name__ == "__main__":
    main()
