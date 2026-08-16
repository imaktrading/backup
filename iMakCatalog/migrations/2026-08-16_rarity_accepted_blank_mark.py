"""「出さないと決めた」17行に判断済マークを付ける (監査の unmapped を新規検知専用にする).

依頼: requests/2026-08-16_rarity_absent_switch_response.md §③④ + 補足
      「rarity_unmapped の日次表示は続けて。③④で 17件は 0 に落ちるはずなので、
        次に増えた時が『新しい未変換が出た』合図になる」

★ HQ の想定と実装が食い違うので埋める:
  ③④ は「出さないと決めた」だけでデータは変わらないため、このままでは
  `rarity_unmapped` は 17 のまま。0 にならないので「次に増えた時」が見えない。
  → 判断済の行に `specs.rarity_ebay_status = 'accepted_blank_20260816'` を付け、
    監査はこれを unmapped から外して別枠 (accepted_blank) で数える。
    結果: rarity_unmapped=0 / accepted_blank=17 となり、**1 でも増えたら新規**と分かる。

対象 (公式に rarity 表記は有るが eBay 表記を決められない / 決めない行):
  - pokemon_tcg  MUR 6 / BWR 2 / C2 1 / U2 1 = 10
      公式はアイコン画像のみで名前を持たない (実測 2026-08-13)。
      HQ 判断 §③「10件のために推測値を入れる価値はない。空欄=出さないで確定」
  - one_piece_tcg `_OP11_dummy` 7
      公式は「SPカード」表記。正しいレコード (_p2 等) が別に在り `Special` を持つため実害なし。
      HQ 判断 §④「触らないでください。重複整理の別件に含める」

値は入れない (= C:Rarity 空のまま = 出品されない)。付けるのは判断済の印だけ。

実行:
  python migrations/2026-08-16_rarity_accepted_blank_mark.py           # dry-run
  python migrations/2026-08-16_rarity_accepted_blank_mark.py --commit
"""
from __future__ import annotations

import argparse
import json
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
STATUS = "accepted_blank_20260816"
CATS = ["pokemon_tcg", "one_piece_tcg", "gundam_tcg", "dragonball_scg"]

NOTE = ("公式に rarity 表記は有るが eBay 表記を決めない/決められないため空欄で確定 "
        "(HQ 判断 2026-08-16 requests/2026-08-16_rarity_absent_switch_response.md §③④)。"
        "推測値を入れない。値が要るようになったら HQ から値付きで依頼が来る。")


def process(commit: bool) -> int:
    print(f"=== rarity 判断済マーク ({'APPLY' if commit else 'DRY-RUN'}) ===")
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    updates = []

    for cat in CATS:
        for r in db.execute("SELECT id, product_id, specs FROM products WHERE category = ?", (cat,)):
            s = json.loads(r["specs"] or "{}")
            # 対象 = 生 rarity は有る / rarity_ebay は空 / まだ判断済マークが無い
            if not s.get("rarity") or s.get("rarity_ebay") or s.get("rarity_ebay_status"):
                continue
            print(f"  {cat:<15} {r['product_id']:<24} rarity={s['rarity']!r}")
            s["rarity_ebay_status"] = STATUS
            s["rarity_ebay_status_note"] = NOTE
            updates.append((json.dumps(s, ensure_ascii=False), NOW, r["id"]))

    print(f"\n対象 {len(updates)} 行")
    if commit:
        db.executemany("UPDATE products SET specs = ?, updated_at = ? WHERE id = ?", updates)
        db.commit()
        print("✅ 適用")
    else:
        print("(dry-run — --commit で適用)")
    db.close()
    return len(updates)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--commit", action="store_true")
    process(p.parse_args().commit)


if __name__ == "__main__":
    main()
