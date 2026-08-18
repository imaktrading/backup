"""rarity 17行の HQ 裁定 (2026-08-18) の回帰アンカー.

回答書: requests/2026-08-13_rarity_17rows_naming_decision_req_response.md [IMPLEMENT-GO]

判定 (1丁目1番地): ① カタログのデータは正しい (生コード = 公式アイコン slug と一致、
公式に長形名は存在しない) → ② 出品くん側 = eBay 表記を HQ が裁定。

裁定 8 値:
  pokemon    MUR → Ultra Rare / BWR → Secret Rare / C2 → Common / U2 → Uncommon
  one_piece  SR SP → Super Rare / SEC SP → Secret Rare / R SP → Rare / SP P → Promo

規約 1 本 (個別カードでなく発生源を直す):
  生コードが空白区切りの '<基底コード> SP' 複合なら **基底コードのマップ値**を採る。
  SP 単独 ('SP' / 'SPカード') だけ 'Special'。基底が未登録なら None = fail-closed 空欄。
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

CATS = ["pokemon_tcg", "one_piece_tcg", "gundam_tcg", "dragonball_scg"]

# 回答書の決定表そのもの (件数込み)
DECIDED = {
    ("pokemon_tcg", "MUR"): ("Ultra Rare", 6),
    ("pokemon_tcg", "BWR"): ("Secret Rare", 2),
    ("pokemon_tcg", "C2"): ("Common", 1),
    ("pokemon_tcg", "U2"): ("Uncommon", 1),
    ("one_piece_tcg", "SR SP"): ("Super Rare", 4),
    ("one_piece_tcg", "SEC SP"): ("Secret Rare", 1),
    ("one_piece_tcg", "R SP"): ("Rare", 1),
    ("one_piece_tcg", "SP P"): ("Promo", 1),
}


def _rows(cat: str):
    db = sqlite3.connect(str(api._DB_PATH))
    out = [json.loads(s or "{}") for (s,) in
           db.execute("SELECT specs FROM products WHERE category = ?", (cat,))]
    db.close()
    return out


class TestDecidedValues:
    def test_all_eight_codes_derive(self):
        for (cat, code), (want, _n) in DECIDED.items():
            assert api.derive_rarity_ebay(cat, code) == want, (cat, code)

    def test_sp_alone_stays_special(self):
        """SP 単独 ('SP' / 'SPカード') は従来どおり 'Special' (規約の例外)."""
        assert api.derive_rarity_ebay("one_piece_tcg", "SP") == "Special"
        assert api.derive_rarity_ebay("one_piece_tcg", "SPカード") == "Special"

    def test_unknown_base_stays_fail_closed(self):
        """基底が未登録なら複合でも None。推測でマッピングを作らない."""
        assert api.derive_rarity_ebay("one_piece_tcg", "ZZZ SP") is None
        assert api.derive_rarity_ebay("pokemon_tcg", "SS") is None

    def test_gundam_concatenated_sp_unaffected(self):
        """gundam の連結形 (空白なし) は yaml 個別登録のまま = 規約の対象外."""
        assert api.derive_rarity_ebay("gundam_tcg", "SPLR") == "Legend Rare"
        assert api.derive_rarity_ebay("gundam_tcg", "SPLR+") == "Legend Rare"


class TestLookupKeys:
    def test_composite_falls_back_to_base(self):
        assert api.rarity_lookup_keys("SR SP") == ["SR SP", "SR"]
        assert api.rarity_lookup_keys("SP P") == ["SP P", "P"]

    def test_single_token_has_no_fallback(self):
        assert api.rarity_lookup_keys("SPカード") == ["SPカード"]
        assert api.rarity_lookup_keys("SP") == ["SP"]

    def test_marker_stripped_first(self):
        assert api.rarity_lookup_keys("LR+") == ["LR"]
        assert api.rarity_lookup_keys("L★") == ["L"]

    def test_empty_is_empty(self):
        assert api.rarity_lookup_keys(None) == []
        assert api.rarity_lookup_keys("  ") == []

    def test_audit_copy_matches_api(self):
        """監査ツールの local 実装が api と同じ順序を返すこと (二重実装の drift 検知)."""
        sys.path.insert(0, str(_REPO / "tools"))
        import set_name_integrity_audit as audit_mod  # noqa: E402

        samples = ["SR SP", "SEC SP", "R SP", "SP P", "SP", "SPカード", "ZZZ SP",
                   "MUR", "LR+", "L★", "SPLR", "C", None, "", "  ", "SP SP"]
        for v in samples:
            assert audit_mod._rarity_lookup_keys(v) == api.rarity_lookup_keys(v), v


class TestDbBackfilled:
    def test_no_row_left_unmapped(self):
        """生 rarity が有って rarity_ebay が空の行は 0 件 (= 監査の unmapped/accepted_blank 0)."""
        left = {}
        for cat in CATS:
            n = sum(1 for s in _rows(cat) if s.get("rarity") and not s.get("rarity_ebay"))
            if n:
                left[cat] = n
        assert left == {}, f"未変換が残っている: {left}"

    def test_decided_rows_have_expected_value_and_count(self):
        for (cat, code), (want, n) in DECIDED.items():
            got = [s.get("rarity_ebay") for s in _rows(cat)
                   if str(s.get("rarity") or "").strip() == code]
            assert len(got) == n, (cat, code, len(got))
            assert set(got) == {want}, (cat, code, set(got))

    def test_accepted_blank_mark_removed_from_filled_rows(self):
        """値が入った行に「出さないと決めた」印が残っていないこと (監査が嘘になる)."""
        bad = []
        for cat in CATS:
            for s in _rows(cat):
                if s.get("rarity_ebay") and s.get("rarity_ebay_status"):
                    bad.append((cat, s.get("rarity"), s.get("rarity_ebay_status")))
        assert bad == [], f"判断済マーク残存: {bad[:5]}"

    def test_no_raw_code_leak_introduced(self):
        """裁定値を入れても生コード漏れ (stored == raw) は 0 のままであること."""
        leaks = {}
        for cat in CATS:
            n = sum(1 for s in _rows(cat)
                    if s.get("rarity") and s.get("rarity_ebay")
                    and str(s["rarity"]).strip() == str(s["rarity_ebay"]).strip())
            if n:
                leaks[cat] = n
        assert leaks == {}, f"生コード漏れ: {leaks}"
