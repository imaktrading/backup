"""dedupe Phase 1i 残失敗 23 件 回収のため未登録 set を ebay_filter_map に追加.

依頼: C:/dev/iMak_data/catalog/requests/2026-05-27_dedupe_unmapped_sets_addition.md

採用 convention (= 既存 set_code 系 row と一致):
- field='set_code': source_value=set_code (internal),  ebay_value=eBay display canonical
- field='set':       source_value=alternate alias (Japanese / eBay 言い換え), ebay_value=canonical

dedupe 側 reverse lookup:
  SELECT source_value FROM ebay_filter_map
   WHERE category=? AND field='set_code' AND ebay_value=<eBay set aspect>
  → 取得した set_code が dedupe key の prefix.
"""
import sqlite3
import sys
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

DB = "C:/dev/iMak_data/catalog/products.sqlite"
NOW = datetime.now().isoformat()
NOTE_SUFFIX = "; dedupe 2026-05-27 追加"

# (category, field, source_value, ebay_value, note)
UPSERTS = [
    # -----------------------------------------------------------------
    # Gundam Card Game
    # -----------------------------------------------------------------
    # GD02 = Dual Impact (既存 row が placeholder 'Wings of Advance' 誤り → 上書き)
    ("gundam_tcg", "set_code", "GD02", "Dual Impact",
     "year=2024; catalog products.set_name='Dual Impact [GD02]' 一致; 旧 'Wings of Advance' から修正" + NOTE_SUFFIX),
    # eBay 出品 alias
    ("gundam_tcg", "set", "Dual Impact", "Dual Impact",
     "eBay 出品 set aspect alias" + NOTE_SUFFIX),
    # Edition Beta Promos = Edition Beta 系 (catalog set_name='Edition Beta', 42 件)
    # 既存 ('Edition Beta' → 'Edition Beta') は field='set' に存在. eBay 出品で 'Promos' 接尾辞付 alias を追加
    ("gundam_tcg", "set", "Edition Beta Promos", "Edition Beta",
     "eBay 出品で 'Promos' 接尾辞付の alias" + NOTE_SUFFIX),

    # -----------------------------------------------------------------
    # Pokemon TCG
    # -----------------------------------------------------------------
    # SM12a = TAG TEAM GX タッグオールスターズ (= Tag Team GX All Stars on eBay)
    ("pokemon_tcg", "set_code", "SM12a", "Tag Team GX All Stars",
     "year=2019; catalog 193 件 'ハイクラスパック「TAG TEAM GX タッグオールスターズ」' 一致" + NOTE_SUFFIX),
    ("pokemon_tcg", "set", "Sun & Moon Tag Team Gx All Stars", "Tag Team GX All Stars",
     "eBay 出品 alias (= 'Sun & Moon' 接頭辞付)" + NOTE_SUFFIX),
    ("pokemon_tcg", "set", "Tag Team GX Tag All Stars", "Tag Team GX All Stars",
     "eBay 出品 alias 表記揺れ" + NOTE_SUFFIX),

    # SM11a = リミックスバウト (= Remix Bout on eBay)
    ("pokemon_tcg", "set_code", "SM11a", "Remix Bout",
     "year=2019; catalog '拡張パック「リミックスバウト」' 一致 (= product_id SM11a-*)" + NOTE_SUFFIX),
    ("pokemon_tcg", "set", "Sun & Moon Remix Bout", "Remix Bout",
     "eBay 出品 alias" + NOTE_SUFFIX),

    # S10b = Pokémon GO (catalog 確認 93 件)
    ("pokemon_tcg", "set_code", "S10b", "Pokémon GO",
     "year=2022; catalog 93 件 '拡張パック「Pokémon GO」' 一致" + NOTE_SUFFIX),
    ("pokemon_tcg", "set", "Go Japanese", "Pokémon GO",
     "eBay 出品 alias 'Go Japanese'" + NOTE_SUFFIX),
    ("pokemon_tcg", "set", "Pokemon GO Japanese", "Pokémon GO",
     "eBay 出品 alias" + NOTE_SUFFIX),

    # M-P prefix = 日本プロモ (M-P-001..M-P-100+). Corociao 系 promo 含む
    # 注: M-P は単一 set でなく Japanese Promo 全般 prefix. set_code 'M-P' で総称
    ("pokemon_tcg", "set_code", "M-P", "Japanese Promo",
     "M-P 系 75 件; プロモカード 総称 prefix (Corociao 等 Battle Collection 同梱 promo 含む)" + NOTE_SUFFIX),
    ("pokemon_tcg", "set", "MP1-Start Deck 100 Battle Collection Corociao", "Japanese Promo",
     "eBay 出品 alias (Corociao 限定 promo)" + NOTE_SUFFIX),

    # Sword & Shield Start Deck 100 — catalog 未登録 (= scrape 未済).
    # set_code 's1a' (公式: スタートデッキ100) が正解だが catalog scrape されてないため、
    # 暫定 alias のみ追加 (set_code は後日 scrape 完了後に追加推奨).
    # → ここでは追加せず response.md に DEFER 記載.

    # -----------------------------------------------------------------
    # One Piece TCG
    # -----------------------------------------------------------------
    # Promo Cards — 既存 4 行 mapping あり (Other Product Card / Promotion Card / プロモーションカード / 限定商品収録カード).
    # eBay 出品 set aspect が直接 'Promo Cards' の場合に dedupe が逆引きできるよう
    # 'Promo Cards' → 'Promo Cards' の self-alias と set_code 'P' を追加.
    ("one_piece_tcg", "set_code", "P", "Promo Cards",
     "OP TCG プロモ総称 prefix (P-XXX series); eBay set aspect 'Promo Cards' 逆引き用" + NOTE_SUFFIX),
    ("one_piece_tcg", "set", "Promo Cards", "Promo Cards",
     "eBay set aspect self-alias (dedupe 逆引き保険)" + NOTE_SUFFIX),

    # Premium Card Collection -Best Selection Vol.2 (1 件) — catalog 未登録
    # → response.md に DEFER 記載 (公式 set scrape 後追加が筋).
]


def main():
    db = sqlite3.connect(DB)
    cur = db.cursor()

    inserted = 0
    updated = 0
    skipped = 0

    for cat, field, src, eb, note in UPSERTS:
        # 既存確認
        existing = cur.execute(
            "SELECT id, ebay_value, note FROM ebay_filter_map WHERE category=? AND field=? AND source_value=?",
            (cat, field, src),
        ).fetchone()

        if existing:
            ex_id, ex_ebay, ex_note = existing
            if ex_ebay == eb:
                print(f"  SKIP (既存一致): {cat}/{field}/{src!r} → {eb!r}")
                skipped += 1
            else:
                # 値が異なる = UPDATE (note に旧値併記)
                merged_note = f"{note}; 旧 ebay_value={ex_ebay!r}"
                cur.execute(
                    "UPDATE ebay_filter_map SET ebay_value=?, note=? WHERE id=?",
                    (eb, merged_note, ex_id),
                )
                print(f"  UPDATE: {cat}/{field}/{src!r}  {ex_ebay!r} → {eb!r}")
                updated += 1
        else:
            cur.execute(
                "INSERT INTO ebay_filter_map (category, field, source_value, ebay_value, note, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (cat, field, src, eb, note, NOW),
            )
            print(f"  INSERT: {cat}/{field}/{src!r} → {eb!r}")
            inserted += 1

    db.commit()
    db.close()

    print(f"\n=== 集計 ===")
    print(f"  INSERT: {inserted}")
    print(f"  UPDATE: {updated}")
    print(f"  SKIP:   {skipped}")


if __name__ == "__main__":
    main()
