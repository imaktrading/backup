"""全 TCG の rarity_ebay 生コード漏れ 是正 (2026-08-13) の回帰アンカー.

指示: ユーザー 2026-08-13「変換されてない生のコードがそのまま eBay に出るのは問題」

公式を実取得して語彙を確定 (2026-08-13):
  - gundam    gundam-gcg.com/{jp,en}/cards/ の rarity filter = C/U/R/LR/LKC/LKU/LKR/P
              '+' は公式語彙に無い刷り違いマーカー。LR の正式名は "Legend Rare"
              (gundam-gcg.com/en/products/gd01.html) → 旧 'Leader Rare' は誤りで是正
  - one_piece onepiece-cardgame.com/cardlist/ = C/UC/R/SR/SEC/L/SPカード
              asia-en 版は同じ位置に "SP CARD" → eBay master 実在値の 'Special' へ
  - pokemon   C_C / U_C / R_C は rarity 画像の type marker 付き別表記 (= C/U/R)

不変条件: **specs.rarity_ebay に公式生コードがそのまま入っている行は 0 件**。
公式長形名が確認できない code (MUR/SS/BWR/C2/U2) は推測せず空欄 = fail-closed。
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO.parent))
sys.path.insert(0, str(_REPO))

from iMakCatalog import api  # noqa: E402

CATS = ["one_piece_tcg", "gundam_tcg", "pokemon_tcg", "dragonball_scg"]


def _rows(cat: str):
    db = sqlite3.connect(str(api._DB_PATH))
    out = [json.loads(s or "{}") for (s,) in
           db.execute("SELECT specs FROM products WHERE category = ?", (cat,))]
    db.close()
    return out


class TestNoRawCodeLeak:
    def test_no_stored_equals_raw(self):
        """変換されていない生コードが rarity_ebay に残っていないこと (全カテゴリ)."""
        leaks = {}
        for cat in CATS:
            n = sum(1 for s in _rows(cat)
                    if s.get("rarity") and s.get("rarity_ebay")
                    and str(s["rarity"]).strip() == str(s["rarity_ebay"]).strip())
            if n:
                leaks[cat] = n
        assert leaks == {}, f"生コード漏れ: {leaks}"

    def test_no_marker_in_stored(self):
        """★ / + の刷り違いマーカーが rarity_ebay に残っていないこと."""
        bad = []
        for cat in CATS:
            for s in _rows(cat):
                v = s.get("rarity_ebay")
                if v and any(ch in str(v) for ch in "★☆+"):
                    bad.append((cat, s.get("rarity"), v))
        assert bad == [], f"マーカー残存: {bad[:5]}"

    def test_no_japanese_in_stored(self):
        """日本語がそのまま eBay facet に出ていないこと (旧 'SPカード' 118件)."""
        bad = []
        for cat in CATS:
            for s in _rows(cat):
                v = str(s.get("rarity_ebay") or "")
                if any(ord(ch) > 0x2FFF for ch in v):
                    bad.append((cat, v))
        assert bad == [], f"日本語残存: {bad[:5]}"


class TestDerive:
    def test_gundam_marker_and_sp(self):
        assert api.derive_rarity_ebay("gundam_tcg", "U") == "Uncommon"
        assert api.derive_rarity_ebay("gundam_tcg", "C+") == "Common"
        assert api.derive_rarity_ebay("gundam_tcg", "LR") == "Legend Rare"
        assert api.derive_rarity_ebay("gundam_tcg", "LR+") == "Legend Rare"
        assert api.derive_rarity_ebay("gundam_tcg", "LR++") == "Legend Rare"
        assert api.derive_rarity_ebay("gundam_tcg", "SPLR+") == "Legend Rare"

    def test_gundam_lr_is_legend_not_leader(self):
        """LR = Legend Rare (公式 EN 商品ページ)。Gundam に Leader カードは無い."""
        assert api.derive_rarity_ebay("gundam_tcg", "LR") != "Leader Rare"
        assert all(s.get("rarity_ebay") != "Leader Rare" for s in _rows("gundam_tcg"))

    def test_one_piece_sp_card_and_leader(self):
        assert api.derive_rarity_ebay("one_piece_tcg", "SPカード") == "Special"
        # 旧 L→"" (空欄) は Leader カードを丸ごと落とす地雷だった
        assert api.derive_rarity_ebay("one_piece_tcg", "L") == "Leader"

    def test_pokemon_type_marker_aliases(self):
        assert api.derive_rarity_ebay("pokemon_tcg", "C_C") == "Common"
        assert api.derive_rarity_ebay("pokemon_tcg", "U_C") == "Uncommon"
        assert api.derive_rarity_ebay("pokemon_tcg", "R_C") == "Rare"

    def test_unknown_codes_stay_fail_closed(self):
        """公式長形名を確認できない code は推測せず None (= 空欄 → 出品側 skip)."""
        for code in ("MUR", "SS", "BWR", "C2", "U2"):
            assert api.derive_rarity_ebay("pokemon_tcg", code) is None, code

    def test_filter_map_has_no_marked_source(self):
        """マーカー付き source_value が filter_map に残っていないこと (古い値を引き続けるため)."""
        db = sqlite3.connect(str(api._DB_PATH))
        rows = db.execute(
            "SELECT category, source_value FROM ebay_filter_map WHERE field = 'rarity'"
        ).fetchall()
        db.close()
        marked = [r for r in rows if api.has_rarity_variant_mark(r[1])]
        assert marked == [], f"マーカー付き map 残存: {marked}"
