"""「出さないと決めた」17行に HQ 裁定の eBay 表記を入れる (accepted_blank → 値あり).

回答書: requests/2026-08-13_rarity_17rows_naming_decision_req_response.md [IMPLEMENT-GO]

判定 (1丁目1番地): **① カタログのデータは正しい → ② 出品くん側 (eBay 表記) を決める**。
生コードは公式アイコン slug (ic_rare_MUR.gif 等) と一字一句一致しており、公式に長形名は
存在しない (HQ が 2026-08-18 に公式を再取得して確認)。よって決めるのは eBay 表記のみ。

HQ 裁定 (8値・全て eBay master cat 183454 の canonical 57 値に実在):
  pokemon    MUR 6 → Ultra Rare / BWR 2 → Secret Rare / C2 1 → Common / U2 1 → Uncommon
  one_piece  SR SP 4 → Super Rare / SEC SP 1 → Secret Rare / R SP 1 → Rare / SP P 1 → Promo

やること:
  1. pokemon は yaml (ebay_filter_map/pokemon.yaml) に 4 entry 追加済 → loader で DB へ
  2. one_piece の '<基底> SP' 複合は個別登録せず api.rarity_lookup_keys() の規約で引く
     (回答書「次から同じ質問が要らないように (規約1本)」)
  3. 本 script が 17 行の specs.rarity_ebay を derive_rarity_ebay() で埋め、
     2026-08-16 に付けた判断済マーク (rarity_ebay_status = accepted_blank_20260816) を外す
     — 値が入った行に「出さないと決めた」印が残ると監査の accepted_blank が嘘になる

事前に必ず: python ebay_filter_map/loader.py pokemon

実行:
  python migrations/2026-08-18_rarity_17rows_hq_decision.py           # dry-run
  python migrations/2026-08-18_rarity_17rows_hq_decision.py --commit
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
SRC_TAG = "rarity_hq_decision_20260818"
CATS = ["pokemon_tcg", "one_piece_tcg", "gundam_tcg", "dragonball_scg"]
STALE_STATUS = "accepted_blank_20260816"


def process(commit: bool) -> int:
    print(f"=== rarity 17行 HQ 裁定反映 ({'APPLY' if commit else 'DRY-RUN'}) ===")

    if commit:
        backup = DB_PATH.with_suffix(f".sqlite.bak_rarity_hq_{datetime.now():%Y%m%d%H%M%S}")
        shutil.copy2(DB_PATH, backup)
        print(f"backup: {backup.name}\n")

    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    updates: list[tuple[str, str, int]] = []
    filled: Counter = Counter()

    for cat in CATS:
        for r in db.execute(
            "SELECT id, product_id, specs FROM products WHERE category = ?", (cat,)
        ):
            s = json.loads(r["specs"] or "{}")
            raw = s.get("rarity")
            # 対象 = 生 rarity は有る / rarity_ebay は空 (値のある行は触らない)
            if not raw or s.get("rarity_ebay"):
                continue
            derived = api.derive_rarity_ebay(cat, raw)
            if derived is None:
                continue  # 裁定の無いコードは空欄のまま (fail-closed)
            print(f"  {cat:<15} {r['product_id']:<24} {raw!r} → {derived!r}")
            s["rarity_ebay"] = derived
            s["rarity_ebay_source"] = SRC_TAG
            # 「出さないと決めた」印は値が入った時点で誤りになるので外す
            if s.get("rarity_ebay_status") == STALE_STATUS:
                s.pop("rarity_ebay_status", None)
                s.pop("rarity_ebay_status_note", None)
            filled[(cat, raw, derived)] += 1
            updates.append((json.dumps(s, ensure_ascii=False), NOW, r["id"]))

    print(f"\n埋めた行 {len(updates)}")
    for (cat, raw, new), c in sorted(filled.items()):
        print(f"  {cat:<15} {raw!r:<12} → {new!r:<14} {c}")

    if commit:
        db.executemany("UPDATE products SET specs = ?, updated_at = ? WHERE id = ?", updates)
        db.commit()
        print("✅ 適用")
        left = Counter()
        for cat in CATS:
            for (sp,) in db.execute("SELECT specs FROM products WHERE category = ?", (cat,)):
                d = json.loads(sp or "{}")
                if d.get("rarity") and not d.get("rarity_ebay"):
                    left[(cat, d["rarity"])] += 1
        print(f"残り (生 rarity 有 / rarity_ebay 空): {sum(left.values())} 件 {dict(left)}")
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
