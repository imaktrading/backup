"""dragonball_scg の specs.rarity_ebay を eBay canonical に是正 (★ は rarity ではない).

依頼: iMak_data/catalog/requests/2026-08-13_dbscg_rarity_ebay_raw_values.md (HQ)

判定 (1丁目1番地): **① 誤 / ② 正** → ① だけを直す。
    出品側は契約 v1.2 §1-1 に従い specs.rarity_ebay をそのまま C:Rarity に入れており正しい。
    誤っていたのは catalog:

    1. 公式 (今その場で再取得 2026-08-13, https://www.dbs-cardgame.com/fw/{jp,en}/cardlist/)
       の rarity filter は **L / C / UC / R / SR / SCR / PR の 7 値のみ**。
       ★ は公式 rarity 語彙に存在せず、parallel / alt-art の刷り違いマーカー。
       detail.php?card_no=FB01-071 も rarity は "L" (★なし) を返す。
    2. それにもかかわらず products.specs.rarity_ebay に ★ 付き生値が 1,164 件残っていた。
       真因 = migrations/2026-05-30_tcg_ebay_fields_phase_b_rarity.py の BANDAI_RARITY に
       ★付きも SCR も無く、resolve_rarity_ebay() が raw fallback で書いたため (カバレッジ穴)。
    3. yaml/filter_map の "L★ → SCR" / "L★★ → SCR" 自体が誤り
       (Leader の parallel を Secret Rare と名乗ることになる)。
    4. 短縮のまま残っていた C→C / UC→UC / R→R / SR→SR / SCR→SCR も
       eBay master (data/ebay_filter_masters/tcg.json cat 183454, 57 canonical 値) に
       実在しない値。master に有るのは Common / Uncommon / Rare / Super Rare / Secret Rare。

実害: cert158452539 (FB01-071_PARA) の C:Rarity が 'L★' → 出品直前の禁止文字除去で 'L' の
      1 文字になり、タイトルも "... Son Gohan : Childhood L" で終わって出品を取り止め。

やること:
  1. ebay_filter_map の誤エントリ (L★ / L★★) を削除 (yaml 側は同時に削除済)
  2. dragonball_scg 全行の specs.rarity_ebay を api.derive_rarity_ebay() で再導出
     (★ を落として filter_map を引く。miss は None = fail-closed、raw に degrade しない)
  3. ★ が付いていた行は Features に 'Alternative Art' を追加
     (2026-07-18 HQ 決定「★ の意味は Features で表現」を consumer 側から producer 側へ移設。
      これが無いと ★ を落とした瞬間に parallel/alt-art の区別が消える)

実行:
  python migrations/2026-08-13_dbscg_rarity_ebay_canonical.py           # dry-run
  python migrations/2026-08-13_dbscg_rarity_ebay_canonical.py --commit  # 適用
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
CAT = "dragonball_scg"
SRC_TAG = "rarity_canonical_20260813"
BEFORE_JSON = Path("C:/dev/iMak_data/catalog/dbscg_rarity_ebay_before_20260813.json")

# yaml から削除した誤エントリ (DB 側も消す)
BAD_MAP_ENTRIES = ["L★", "L★★"]

ALT_ART_FEATURE = "Alternative Art"
# 既に等価な値を持っている行には足さない (derive_features は 'Alt Art' 表記で書いている)
ALT_ART_EQUIV = {"Alternative Art", "Alt Art"}


def _star(rarity_raw: str | None) -> bool:
    return bool(rarity_raw) and "★" in rarity_raw


def process(commit: bool) -> int:
    print(f"=== dbscg rarity_ebay canonical ({'APPLY' if commit else 'DRY-RUN'}) ===")

    if commit:
        backup = DB_PATH.with_suffix(f".sqlite.bak_rarity_{datetime.now():%Y%m%d%H%M%S}")
        shutil.copy2(DB_PATH, backup)
        print(f"backup: {backup.name}")

    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row

    # --- 1) 誤 filter_map エントリの削除 -----------------------------------
    for bad in BAD_MAP_ENTRIES:
        row = db.execute(
            "SELECT ebay_value FROM ebay_filter_map "
            "WHERE category = ? AND field = 'rarity' AND source_value = ?",
            (CAT, bad),
        ).fetchone()
        if row:
            print(f"  filter_map 削除: {bad!r} → {row['ebay_value']!r} (誤り)")
            if commit:
                db.execute(
                    "DELETE FROM ebay_filter_map "
                    "WHERE category = ? AND field = 'rarity' AND source_value = ?",
                    (CAT, bad),
                )

    # --- 2) rarity_ebay 再導出 --------------------------------------------
    rows = db.execute(
        "SELECT id, product_id, specs FROM products WHERE category = ?", (CAT,)
    ).fetchall()

    before: list[dict] = []
    changes = Counter()
    feat_added = 0
    unmapped = Counter()
    updates: list[tuple[str, str, int]] = []

    for r in rows:
        specs = json.loads(r["specs"] or "{}")
        raw = specs.get("rarity")
        cur = specs.get("rarity_ebay")
        new = api.derive_rarity_ebay(CAT, raw)

        feats = list(specs.get("features") or [])
        new_feats = feats
        if _star(raw) and not (ALT_ART_EQUIV & set(feats)):
            new_feats = feats + [ALT_ART_FEATURE]

        if new == cur and new_feats == feats:
            continue

        if raw and new is None:
            unmapped[raw] += 1
            # fail-closed: filter_map に無い rarity は書き換えない (raw を残して可視化)
            continue

        before.append({"product_id": r["product_id"], "rarity": raw,
                       "rarity_ebay": cur, "features": feats})
        changes[(cur, new)] += 1
        if new_feats != feats:
            feat_added += 1

        specs["rarity_ebay"] = new
        specs["features"] = new_feats
        specs["rarity_ebay_source"] = SRC_TAG
        updates.append((json.dumps(specs, ensure_ascii=False), NOW, r["id"]))

    print(f"\n変更対象: {len(updates)} 行 (features 追加 {feat_added} 行)")
    for (old, new), n in changes.most_common():
        print(f"  {str(old):<12} → {str(new):<14} {n}")
    if unmapped:
        print("\n⚠️ filter_map 未登録で据え置き (fail-closed):")
        for k, n in unmapped.most_common():
            print(f"  {k!r}: {n}")

    if commit:
        BEFORE_JSON.write_text(json.dumps(before, ensure_ascii=False, indent=1),
                               encoding="utf-8")
        db.executemany(
            "UPDATE products SET specs = ?, updated_at = ? WHERE id = ?", updates
        )
        db.commit()
        print(f"\n✅ {len(updates)} 行を更新。 before: {BEFORE_JSON}")

        after = Counter()
        for (s,) in db.execute("SELECT specs FROM products WHERE category = ?", (CAT,)):
            after[json.loads(s or "{}").get("rarity_ebay")] += 1
        print("\n更新後 rarity_ebay 分布:")
        for k, n in after.most_common():
            print(f"  {str(k):<16} {n}")
        star_left = sum(n for k, n in after.items() if k and "★" in k)
        print(f"\n★ 残存: {star_left} 件")
    else:
        print("\n(dry-run — --commit で適用)")

    db.close()
    return len(updates)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--commit", action="store_true")
    process(p.parse_args().commit)


if __name__ == "__main__":
    main()
