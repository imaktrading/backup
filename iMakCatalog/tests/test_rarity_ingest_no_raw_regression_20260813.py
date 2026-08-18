"""生 rarity コードの **再流入経路** を塞いだことの回帰アンカー (2026-08-13).

1,238 行を是正しても、新弾取込のたびに raw を書き戻す経路が残っていれば再発する
(= 既知の「事故→パッチ」ループ)。取込側 2 経路を fail-closed 化した:

  A. migrations/2026-05-30_tcg_ebay_fields_phase_b_rarity.py
     旧: 辞書に無いコードを `return rarity_raw` で raw fallback
     新: ebay_filter_map から導出し、未登録は None (空欄) を返す
     ※ 新弾取込フロー (memory: tcg_newset_ingest_flow) が毎回走らせる migration

  B. migrations/2026-05-30_dbfw_official_import.py `_derive_leader_rarity`
     旧: alt_art LEADER に ('L★','L★') = rarity_ebay に生値を書いていた
     新: rarity_ebay は api.derive_rarity_ebay() 経由 ('Leader')
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO.parent))
sys.path.insert(0, str(_REPO))


def _load(rel: str, name: str):
    spec = importlib.util.spec_from_file_location(name, _REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestPhaseBNoRawFallback:
    def setup_method(self):
        self.m = _load("migrations/2026-05-30_tcg_ebay_fields_phase_b_rarity.py", "_phase_b")

    def test_unknown_code_is_none_not_raw(self):
        """辞書にも filter_map にも無いコードは None。raw を返さない.

        ★2026-08-18: pokemon 'MUR' / one_piece 'SR SP' は HQ 裁定で map 済になったので
        未登録サンプルを差し替えた (test_rarity_sp_composite_20260818.py が裁定側を検査)。
        """
        for cat, code in (("gundam_tcg", "ZZZ"), ("pokemon_tcg", "SS"),
                          ("one_piece_tcg", "ZZZ SP"), ("dragonball_scg", "QQ")):
            assert self.m.resolve_rarity_ebay(cat, code) is None, (cat, code)

    def test_marker_codes_are_canonical(self):
        """★ / + 付きは base の canonical に落ちる (raw のまま返らない)."""
        assert self.m.resolve_rarity_ebay("dragonball_scg", "L★") == "Leader"
        assert self.m.resolve_rarity_ebay("gundam_tcg", "C+") == "Common"
        assert self.m.resolve_rarity_ebay("gundam_tcg", "SPLR+") == "Legend Rare"

    def test_known_codes_still_resolve(self):
        assert self.m.resolve_rarity_ebay("one_piece_tcg", "SEC") == "Secret Rare"
        # '<基底> SP' 複合は基底に落ちる (HQ 裁定 2026-08-18)。取込経路でも効くこと
        assert self.m.resolve_rarity_ebay("one_piece_tcg", "SR SP") == "Super Rare"
        assert self.m.resolve_rarity_ebay("pokemon_tcg", "MUR") == "Ultra Rare"
        assert self.m.resolve_rarity_ebay("one_piece_tcg", "SPカード") == "Special"
        assert self.m.resolve_rarity_ebay("pokemon_tcg", "RR") == "Double Rare"
        assert self.m.resolve_rarity_ebay("gundam_tcg", "LR") == "Legend Rare"

    def test_canonical_longform_passes_through(self):
        assert self.m.resolve_rarity_ebay("pokemon_tcg", "Common") == "Common"

    def test_yugioh_stays_passthrough(self):
        """YGO の生値は既に英語 canonical なので passthrough が正."""
        assert self.m.resolve_rarity_ebay("yugioh_tcg", "Secret Rare") == "Secret Rare"


class TestDbfwIngestLeaderRarity:
    def setup_method(self):
        self.m = _load("migrations/2026-05-30_dbfw_official_import.py", "_dbfw_import")

    def test_alt_art_leader_gets_canonical_not_raw(self):
        got = self.m._derive_leader_rarity("FB07-097_p1", {"card_type": "LEADER",
                                                           "variant_type": "alt_art"})
        assert got == ("L★", "Leader"), got   # 旧: ('L★','L★') = 生値漏れ

    def test_base_leader_unchanged(self):
        got = self.m._derive_leader_rarity("FB01-001", {"card_type": "LEADER",
                                                        "variant_type": None})
        assert got == ("L", "Leader")

    def test_denylist_still_fail_closed(self):
        got = self.m._derive_leader_rarity("FP-030", {"card_type": "LEADER",
                                                      "variant_type": None})
        assert got is None
