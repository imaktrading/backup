#!/usr/bin/env python3
"""character_name scramble 91件を Option A (character_name = name_en) で一括是正.

HQ decision `2026-06-14_character_name_scramble_91_OptionA_decision.md` (GO)。
監査検査4 が検出した scramble (character_name が別カードの name_en にズレて入った) を是正。

Option A 根拠 (HQ 実機確認):
  - 新生成コア iMakTCG/tcg_listing_fields.py:174-177 は C:Character=character_name を無加工使用、
    character_name==name_en を前提 (コメントで name_en≠character_name=catalog内部不整合と明記)。
  - 実 DB 慣習も character_name = name_en (全 card_type, verbatim)。
  - = name_en コピーで scramble是正 + desync解消 + 無加工ポリシー一致 を同時達成。
  - 「種名strip / trainer空」方針は撤回 (新コアに無い処理・無加工ポリシー違反)。

対象特定 = set_name_integrity_audit.py 検査4 と同一述語 (両非空・ne!=cn・接頭辞非一致)。
specs 列のみ直接 UPDATE (upsert は images/name を上書きするため使わない)。.bak 必須。
"""
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

DB_PATH = "C:/dev/iMak_data/catalog/products.sqlite"
BAK_PATH = Path("C:/dev/iMak_data/catalog/_bak/character_name_scramble_rederive_before_20260614.json")
CATEGORY = "pokemon_tcg"


def is_desync(ne, cn) -> bool:
    """検査4 と同一述語: 両非空・不一致・どちらも接頭辞でない (真の scramble)."""
    return bool(ne and cn and ne != cn
                and not ne.startswith(cn) and not cn.startswith(ne))


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    dry = "--apply" not in sys.argv
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, product_id, name_en, specs FROM products WHERE category=?",
        (CATEGORY,),
    ).fetchall()

    bak = {}
    changes = []
    for r in rows:
        s = json.loads(r["specs"])
        ne, cn = r["name_en"], s.get("character_name")
        if not is_desync(ne, cn):
            continue
        bak[r["product_id"]] = cn  # 旧 character_name を保存
        s["character_name"] = ne   # Option A: name_en コピー
        ct = s.get("card_type")
        changes.append((r["product_id"], cn, ne, ct))
        if not dry:
            now = datetime.now().isoformat(timespec="seconds")
            conn.execute(
                "UPDATE products SET specs=?, updated_at=? WHERE id=?",
                (json.dumps(s, ensure_ascii=False), now, r["id"]),
            )

    from collections import Counter
    print(f"=== 対象 {len(changes)} 件 (card_type別: {dict(Counter(c[3] for c in changes))}) ===")
    for pid, old, new, ct in changes:
        print(f"  {pid:14} [{ct}] character_name: {old!r} → {new!r}")

    if dry:
        print(f"\n[DRY-RUN] DB 未変更。投入は --apply。")
        conn.close()
        return

    BAK_PATH.parent.mkdir(parents=True, exist_ok=True)
    BAK_PATH.write_text(json.dumps(bak, ensure_ascii=False, indent=2), encoding="utf-8")
    conn.commit()
    conn.close()
    print(f"\n✅ 是正完了 ({len(changes)} 件)。bak: {BAK_PATH}")


if __name__ == "__main__":
    main()
