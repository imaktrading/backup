#!/usr/bin/env python3
"""日本版セット名に戻す + 2セットが1つに潰れていたのを分ける.

決定: requests/2026-08-21_english_set_name_on_jp_cards_hq_verdict.md [IMPLEMENT-GO]
      (出品くんが20組を1組ずつ検証。カタログ側で eBay リストに再照合して実施)

## 変換表の修正 (先にこれを直さないと products を壊す)

| 変更 | 前 | 後 | 根拠 |
|---|---|---|---|
| set_code MC | Movie Promo | Start Deck 100 Battle Collection | 公式名=スタートデッキ100 バトルコレクション。Movie Promo は eBay にも無い |
| set_code SV2a | Pokemon 151 | Sv2a: Pokemon Card 151 | eBay に在る (Pokemon 151 は無い) |
| set_code SM11a | Sun & Moon Remix Bout | Sm11a: Remix Bout | eBay に在る |

## 2セットが1つに潰れていた分を分ける (新規4行 + 2行)

set_code だけで引くと、同じ弾番号を共有する日本版2セットが**片方に寄る**。
例: BW6 は「フリーズボルト」と「コールドフレア」の2つなのに、両方 Freeze Bolt になっていた
(= 59件が別セットとして出品されるところだった)。
公式原文は2つで別なので、`set` (公式原文ベタ一致) に足せば分かれる。

  コールドフレア            -> Bw6: Cold Flare        (eBay に在る)
  タイダルストーム          -> Tidal Storm            (eBay に無し=凍結)
  コレクションY             -> Collection Y           (eBay に無し=凍結)
  ソウルシルバーコレクション -> SoulSilver Collection  (eBay に無し=凍結)

★eBay に無い3つは**造語ではありません**。bulbapedia で
  `Tidal_Storm_(TCG)` / `Collection_Y_(TCG)` / `SoulSilver_Collection_(TCG)` が
  それぞれ対応する英語版セットのページに転送されることを実取得で確認 (2026-08-21)。
  既に使っている対の側 (Gaia Volcano / Collection X / HeartGold Collection) と同じ確かめ方。

さらに 25th 系2件 (出品くんが「要決定」としていた分。eBay リストに在ったので確定):

  25th ANNIVERSARY GOLDEN BOX          -> 25th Anniversary Golden Box
  プロモカードパック 25th ANNIVERSARY edition -> S8a-P: Promo Card Pack 25th Anniversary Edition

## products の焼き直し

上の修正後、対象20組の行だけ `specs.set_name_ebay` を導出値に合わせる。
**対象を stored 値の allowlist で絞る** (全件 restamp はしない)。

実行:
  python migrations/2026-08-21_jp_set_name_restore_and_splits.py           # dry-run
  python migrations/2026-08-21_jp_set_name_restore_and_splits.py --commit
"""
from __future__ import annotations

import argparse
import json
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

NOW = datetime.now().isoformat()
VERIFY = "ebay_getItemAspectsForCategory_183454+hq_verdict_20260821"

# (field, source_value, 新しい ebay_value)
MAP_FIX = [
    ("set_code", "MC",     "Start Deck 100 Battle Collection"),
    ("set_code", "SV2a",   "Sv2a: Pokemon Card 151"),
    ("set_code", "SM11a",  "Sm11a: Remix Bout"),
]

MAP_ADD = [
    ("set", "ポケモンカードゲームBW 拡張パック「コールドフレア」", "Bw6: Cold Flare"),
    ("set", "ポケモンカードゲームXY 拡張パック「タイダルストーム」", "Tidal Storm"),
    ("set", "ポケモンカードゲームXY 拡張パック「コレクションY」", "Collection Y"),
    ("set", "ポケモンカードゲームLEGEND 拡張パック「ソウルシルバーコレクション」", "SoulSilver Collection"),
    ("set", "25th ANNIVERSARY GOLDEN BOX", "25th Anniversary Golden Box"),
    ("set", "プロモカードパック 25th ANNIVERSARY edition",
     "S8a-P: Promo Card Pack 25th Anniversary Edition"),
]

# 焼き直しの対象 = この stored 値を持つ行だけ (出品くんが検証した20組)
TARGET_STORED = {
    "SV: Paldean Fates", "Shining Fates", "Crown Zenith", "Hidden Fates",
    "Sv07: Stellar Crown", "Sv06: Twilight Masquerade", "Sv10: Destined Rivals",
    "SV04: Paradox Rift", "Sv: Shrouded Fable", "Celebrations",
    "Scarlet & Violet—151", "Start Deck 100 Battle Collection", "Sm11a: Remix Bout",
    "Boundaries Crossed", "XY - Primal Clash", "XY", "HeartGold & SoulSilver",
    "Promo", "25th Anniversary Golden Box",
}


def fix_map(db, commit):
    print("--- 変換表の修正")
    for field, src, new in MAP_FIX:
        r = db.execute("SELECT id, ebay_value FROM ebay_filter_map WHERE category='pokemon_tcg' "
                       "AND field=? AND source_value=?", (field, src)).fetchone()
        if r is None:
            print("  ✗ %s %r が無い → skip" % (field, src))
            continue
        if r["ebay_value"] == new:
            print("  - %s %r 既に %r" % (field, src, new))
            continue
        print("  ~ %s %-8r %r -> %r" % (field, src, r["ebay_value"], new))
        if commit:
            db.execute("UPDATE ebay_filter_map SET ebay_value=?, verified_at=?, verify_source=? "
                       "WHERE id=?", (new, NOW, VERIFY, r["id"]))

    print("--- 変換表への追加 (2セットが潰れていた分)")
    for field, src, new in MAP_ADD:
        r = db.execute("SELECT id FROM ebay_filter_map WHERE category='pokemon_tcg' "
                       "AND field=? AND source_value=?", (field, src)).fetchone()
        if r:
            print("  - 既に在る: %r" % src)
            continue
        print("  + %r -> %r" % (src, new))
        if commit:
            db.execute("INSERT INTO ebay_filter_map (category, field, source_value, ebay_value, "
                       "note, created_at, status, verified_at, verify_source) "
                       "VALUES (?,?,?,?,?,?,?,?,?)",
                       ("pokemon_tcg", field, src, new,
                        "2026-08-21 潰れていた日本版セットを分離", NOW, "B", NOW, VERIFY))
    if commit:
        # 先に確定させる。api.to_ebay_value は毎回 DB を読む (キャッシュ無し) ので、
        # ここで commit しておけば次の restamp は新しい表を見る。
        db.commit()


def restamp(db, commit):
    print("\n--- products の焼き直し (対象 stored のみ)")
    pairs = Counter()
    updates = []
    for r in db.execute("SELECT id, category, product_id, set_name_official, specs FROM products "
                        "WHERE category='pokemon_tcg' AND set_name_official IS NOT NULL"):
        s = json.loads(r["specs"] or "{}")
        stored = s.get("set_name_ebay")
        if stored not in TARGET_STORED:
            continue
        derived = api.derive_set_name_ebay(r["category"], r["set_name_official"], r["product_id"])
        if not derived or derived == stored:
            continue
        pairs[(stored, derived)] += 1
        s["set_name_ebay"] = derived
        s["set_name_ebay_source"] = "jp_set_name_restore_20260821"
        updates.append((json.dumps(s, ensure_ascii=False), NOW, r["id"]))

    for (st, de), n in pairs.most_common():
        print("  %-34s -> %-40s %d" % (st, de, n))
    print("  合計 %d 行 / %d 組" % (len(updates), len(pairs)))

    if commit and updates:
        db.executemany("UPDATE products SET specs=?, updated_at=? WHERE id=?", updates)
        db.commit()
        print("  [OK] 適用")
    return len(updates)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()
    db = sqlite3.connect(api._DB_PATH)
    db.row_factory = sqlite3.Row
    print("=== 日本版セット名の復元 + 分離 (%s) ===" % ("APPLY" if args.commit else "DRY-RUN"))
    fix_map(db, args.commit)
    if not args.commit:
        print("\n★dry-run では変換表が未修正のため、下の焼き直しは本実行と一致しません")
    restamp(db, args.commit)
    db.close()
    if not args.commit:
        print("\n(dry-run — --commit で適用)")


if __name__ == "__main__":
    main()
