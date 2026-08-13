"""生コードが C:Rarity に漏れている行を全 TCG で是正 (dragonball 以外の 997 行).

依頼: ユーザー指示 2026-08-13「変換されてない生のコードがそのまま eBay に出るのは問題」
      (requests/2026-08-13_dbscg_rarity_ebay_raw_values_response.md で報告した残件)

判定 (1丁目1番地): **① 誤**。catalog が eBay 派生値を作りきれておらず、
`resolve_rarity_ebay()` の raw fallback で公式生コードが specs.rarity_ebay に焼かれていた。

公式を今その場で再取得して語彙を確定 (2026-08-13):
  - gundam    https://www.gundam-gcg.com/{jp,en}/cards/  rarity filter = C/U/R/LR/LKC/LKU/LKR/P
              '+' は公式語彙に無い = 刷り違い (parallel) マーカー
              LR の正式名は "Legend Rare" (gundam-gcg.com/en/products/gd01.html)
              → 旧 'Leader Rare' は One Piece の LR を持ち込んだ誤りなので是正
  - one_piece https://www.onepiece-cardgame.com/cardlist/     → C/UC/R/SR/SEC/L/SPカード
              https://asia-en.onepiece-cardgame.com/cardlist/ → 同じ位置に "SP CARD"
              → SPカード は公式 rarity。eBay master 実在値の 'Special' に寄せる
  - pokemon   rarity 画像コード。C_C/U_C/R_C は scraper の type marker 付き別表記 (= C/U/R)

やること (category 横断):
  1. specs.rarity_ebay を api.derive_rarity_ebay() で再導出
  2. **stored == raw (= 未変換の生コード) の行だけ**、導出できなければ None にして漏れを止める
     (fail-closed。長形が入っている行は filter_map 未登録でも触らない = 誤破壊防止)
  3. 刷り違いマーカー (★ / +) が付いていた行は Features に 'Alternative Art' を追加

実行:
  python migrations/2026-08-13_tcg_rarity_ebay_canonical_all.py           # dry-run
  python migrations/2026-08-13_tcg_rarity_ebay_canonical_all.py --commit  # 適用
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
SRC_TAG = "rarity_canonical_20260813"
BEFORE_JSON = Path("C:/dev/iMak_data/catalog/tcg_rarity_ebay_before_20260813.json")

CATEGORIES = ["one_piece_tcg", "gundam_tcg", "pokemon_tcg", "dragonball_scg"]

ALT_ART_FEATURE = "Alternative Art"
ALT_ART_EQUIV = {"Alternative Art", "Alt Art"}

# yaml から外した「変換になっていない」エントリ (source == ebay の生コード) を DB からも消す。
# loader は upsert なので yaml で消しただけでは DB に残り、生値漏れが続くため。
# 注: 恒等でも 'Special'→'Special' のように eBay master 実在値なら正しいので個別に指定する。
BAD_MAP_ENTRIES = [
    ("pokemon_tcg", "MUR"),   # 公式長形名を確認できず → 未登録にして fail-closed 空欄へ
]


def process(commit: bool) -> int:
    print(f"=== TCG rarity_ebay canonical ({'APPLY' if commit else 'DRY-RUN'}) ===")

    if commit:
        backup = DB_PATH.with_suffix(f".sqlite.bak_rarity_all_{datetime.now():%Y%m%d%H%M%S}")
        shutil.copy2(DB_PATH, backup)
        print(f"backup: {backup.name}\n")

    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row

    # 刷り違いマーカー付きの source_value (LR+ / SPLR+ / L★ …) はマーカーを落としてから
    # 引く運用になったので filter_map 側に残っていてはいけない (残ると古い値を引き続ける)。
    marked = [(r["category"], r["source_value"]) for r in db.execute(
        "SELECT category, source_value FROM ebay_filter_map WHERE field = 'rarity'"
    ) if api.has_rarity_variant_mark(r["source_value"])]
    for cat, src in marked + BAD_MAP_ENTRIES:
        row = db.execute(
            "SELECT ebay_value FROM ebay_filter_map "
            "WHERE category = ? AND field = 'rarity' AND source_value = ?", (cat, src)
        ).fetchone()
        if row:
            print(f"  filter_map 削除: {cat} {src!r} → {row['ebay_value']!r} (変換になっていない)")
            if commit:
                db.execute(
                    "DELETE FROM ebay_filter_map "
                    "WHERE category = ? AND field = 'rarity' AND source_value = ?", (cat, src)
                )
                db.commit()

    before: list[dict] = []
    updates: list[tuple[str, str, int]] = []
    total_cleared = 0

    for cat in CATEGORIES:
        rows = db.execute(
            "SELECT id, product_id, specs FROM products WHERE category = ?", (cat,)
        ).fetchall()
        changes: Counter = Counter()
        cleared: Counter = Counter()
        feat_added = 0

        for r in rows:
            specs = json.loads(r["specs"] or "{}")
            raw = specs.get("rarity")
            cur = specs.get("rarity_ebay")
            if not raw:
                continue

            derived = api.derive_rarity_ebay(cat, raw)
            is_raw_stamped = cur is not None and str(raw).strip() == str(cur).strip()

            if derived is not None:
                new = derived
            elif is_raw_stamped:
                new = None          # 生コード漏れを止める (fail-closed = 空欄 → 出品側 skip)
            else:
                continue            # 長形が入っている行は filter_map 未登録でも触らない

            feats = list(specs.get("features") or [])
            new_feats = feats
            if api.has_rarity_variant_mark(raw) and not (ALT_ART_EQUIV & set(feats)):
                new_feats = feats + [ALT_ART_FEATURE]

            if new == cur and new_feats == feats:
                continue

            before.append({"category": cat, "product_id": r["product_id"], "rarity": raw,
                           "rarity_ebay": cur, "features": feats})
            if new is None:
                cleared[raw] += 1
            else:
                changes[(cur, new)] += 1
            if new_feats != feats:
                feat_added += 1

            specs["rarity_ebay"] = new
            specs["features"] = new_feats
            specs["rarity_ebay_source"] = SRC_TAG
            updates.append((json.dumps(specs, ensure_ascii=False), NOW, r["id"]))

        n = sum(changes.values()) + sum(cleared.values())
        print(f"--- {cat}: {n} 行 (features 追加 {feat_added})")
        for (old, new), c in changes.most_common(20):
            print(f"      {str(old):<16} → {str(new):<16} {c}")
        for raw, c in cleared.most_common(20):
            print(f"      {str(raw):<16} → (空欄, fail-closed) {c}")
        total_cleared += sum(cleared.values())

    print(f"\n合計 {len(updates)} 行 (うち空欄化 {total_cleared} 行)")

    if commit:
        # 再実行 (0 行) で既存の before スナップショットを空で潰さない
        if before:
            BEFORE_JSON.write_text(json.dumps(before, ensure_ascii=False, indent=1),
                                   encoding="utf-8")
        else:
            print("(変更 0 行 → before JSON は既存を維持)")
        db.executemany("UPDATE products SET specs = ?, updated_at = ? WHERE id = ?", updates)
        db.commit()
        print(f"✅ 適用。 before: {BEFORE_JSON}")

        print("\n更新後の生コード残り (stored == raw):")
        for cat in CATEGORIES:
            left: Counter = Counter()
            for (s,) in db.execute("SELECT specs FROM products WHERE category = ?", (cat,)):
                d = json.loads(s or "{}")
                raw, cur = d.get("rarity"), d.get("rarity_ebay")
                if raw and cur and str(raw).strip() == str(cur).strip():
                    left[raw] += 1
            print(f"  {cat}: {sum(left.values())} 件 {dict(left.most_common(5))}")
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
