"""表記規約22セット (現行 20 official / 15 set / 2,051行) を **コード形** に再生成.

回答書: requests/2026-08-10_tcg_ssot_a4_result_and_one_decision_req_response.md [IMPLEMENT-GO]

判定 (1丁目1番地): **① カタログのデータは正しい → ② 出品くん側 (eBay 表記) を決める**。
生値 (set_name_official = 公式原文『拡張パック「ロストアビス」』等) は公式のままで誤りは無く、
どちらの候補も eBay master (cat 183454 / 2,290値) に実在する。決めるのは
「master に2表記あるとき、どちらを C:Set に出すか」= ② の表記選択だけ。

決定: **コード形** (`Swsh11: Lost Origin` / `SV03: Obsidian Flames`)。
根拠は HQ が 2026-08-18 に eBay 本番 API で実測した出品件数:
  Lost Origin 171,639 (コード形) vs 22,904 (`Sword & Shield - Lost Origin`) = 7.5倍
  Obsidian Flames 176,034 vs 23,179 = 7.6倍 / 素名が相手の場合は差 10% 以内
  → 「コード形は最悪でも引き分け、長形相手には圧勝」。

2026-08-11 の Advisor 暫定 GO (長形) を上書きする。上書きしてよい理由は暫定 GO 自身が
「どちらの表記に出品が多く集まっているかは測れていません (403)。**後で分かれば戻せる範囲の
判断です**」と明記しているため。本 migration がその「後で分かった」に当たる。

対象外 (意図的に触らない):
  - `Si: Start Deck 100` / `CP4: Premium Champion Pack`
      → 2026-08-11 回答 §3「テストが在る＝意図的な値」で現状維持。表記選択の22セットとは別件
  - `25th Anniversary Golden Box`  → 同 §2 現状維持
  - `Double Crisis`
      → master の対抗値は `CP1: Magma Gang vs Aqua Gang: Double Crisis` で
        **コード接頭辞を足しただけではない別名**。HQ の実測表にも無く「2表記の選択」に
        当たらないため保留 (勝手に寄せない)

書く値は **必ず master 2,290値の verbatim**。組み立てない (`SV02:` は master に無く
`Sv02:` が正)。1文字違っても eBay は**エラーを返さず**カテゴリ全件が返るため、
書込前に master 完全一致チェックを通す (通らなければ 1行も書かずに中断)。

事前に必ず: python ebay_filter_map/loader.py pokemon

実行:
  python migrations/2026-08-18_set_name_ebay_codeform_hq_decision.py            # dry-run
  python migrations/2026-08-18_set_name_ebay_codeform_hq_decision.py --commit
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
MASTER = ROOT / "data/ebay_filter_masters/tcg.json"
SRC_TAG = "hq_codeform_decision_20260818"
CATEGORY = "pokemon_tcg"

# 対象 = 「長形/素名 → コード形」の 15 set。値は master verbatim (組み立て禁止)。
CODEFORM = {
    "Sword & Shield - Battle Styles":     "Swsh05: Battle Styles",
    "Sword & Shield - Chilling Reign":    "Swsh06: Sword & Shield - Chilling Reign",
    "Sword & Shield - Lost Origin":       "Swsh11: Lost Origin",
    "Sword & Shield - Silver Tempest":    "Swsh12: Sword & Shield - Silver Tempest",
    "Scarlet & Violet - Obsidian Flames": "SV03: Obsidian Flames",
    "Prismatic Evolutions":               "Sv: Prismatic Evolutions",
    "Journey Together":                   "Sv09: Journey Together",
    "Astral Radiance":                    "Swsh10: Astral Radiance",
    "Fusion Strike":                      "Swsh08: Fusion Strike",
    "Vivid Voltage":                      "Swsh04: Vivid Voltage",
    "Darkness Ablaze":                    "Swsh03: Darkness Ablaze",
    "Rebel Clash":                        "Swsh02: Rebel Clash",
    "Evolving Skies":                     "SWSH07: Evolving Skies",
    "Shining Legends":                    "Sm3+: Shining Legends",
    "Pokémon GO":                         "S10b: Pokémon GO",
}
EXPECTED_ROWS = 2051


def _master_values() -> set:
    return set(json.loads(MASTER.read_text(encoding="utf-8"))["aspects"]["Set"]["values"])


def process(commit: bool) -> int:
    print(f"=== 表記規約22セット → コード形 ({'APPLY' if commit else 'DRY-RUN'}) ===")

    # ① 書く値が master に実在するか (fail-closed: 1つでも外れたら何も書かない)
    master = _master_values()
    missing = sorted(v for v in CODEFORM.values() if v not in master)
    if missing:
        print(f"❌ master 非実在の値があるため中断: {missing}")
        return 0
    print(f"master 照合 OK ({len(CODEFORM)} 値 / master {len(master)} 値)")

    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    now = datetime.now().isoformat()
    updates: list[tuple[str, str, int]] = []
    changed: Counter = Counter()

    for r in db.execute(
        "SELECT id, product_id, set_name_official, specs FROM products WHERE category = ?",
        (CATEGORY,),
    ):
        s = json.loads(r["specs"] or "{}")
        old = s.get("set_name_ebay")
        if old not in CODEFORM:
            continue
        new = CODEFORM[old]
        # map からの導出と一致することを 1行ずつ確認 (yaml=SSOT / 焼き込みとの乖離を作らない)
        derived = api.derive_set_name_ebay(CATEGORY, r["set_name_official"], r["product_id"])
        if derived != new:
            print(f"❌ map 導出と不一致のため中断: {r['product_id']} "
                  f"official={r['set_name_official']!r} derived={derived!r} 期待={new!r}")
            return 0
        s["set_name_ebay"] = new
        s["set_name_ebay_source"] = SRC_TAG
        changed[(old, new)] += 1
        updates.append((json.dumps(s, ensure_ascii=False), now, r["id"]))

    for (old, new), n in sorted(changed.items(), key=lambda x: -x[1]):
        print(f"  {n:5d}  {old!r} → {new!r}")
    print(f"\n更新対象 {len(updates)} 行 / {len(changed)} set (期待 {EXPECTED_ROWS} 行)")

    if len(updates) != EXPECTED_ROWS:
        print(f"❌ 行数が期待値と違うため中断 (実測 {len(updates)} / 期待 {EXPECTED_ROWS})")
        return 0

    if not commit:
        print("(dry-run — --commit で適用)")
        db.close()
        return len(updates)

    backup = DB_PATH.with_suffix(f".sqlite.bak_codeform_{datetime.now():%Y%m%d%H%M%S}")
    shutil.copy2(DB_PATH, backup)
    print(f"backup: {backup.name}")

    db.executemany("UPDATE products SET specs = ?, updated_at = ? WHERE id = ?", updates)
    db.commit()

    left = sum(1 for (sp,) in db.execute(
        "SELECT specs FROM products WHERE category = ?", (CATEGORY,))
        if json.loads(sp or "{}").get("set_name_ebay") in CODEFORM)
    print(f"✅ 適用 / 長形の残り {left} 行")
    db.close()
    return len(updates)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--commit", action="store_true")
    process(p.parse_args().commit)


if __name__ == "__main__":
    main()
