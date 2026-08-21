# -*- coding: utf-8 -*-
"""目視「該当なし」→ catalog依頼 の経路に、閉じる出口を作る (2026-08-21).

★実害: 目視で「該当なし」と押されると、catalog に行が在っても
  「兄弟 variant が欠けている」と断定して依頼に流していた。
  ところが cert78976849 (かがやくイーブイ) は **人の見間違い**で、
  求めている variant は実在しない。**この依頼は永久に閉じられない**。

  公式スキャンはホロの虹格子で絵柄が白飛びし、PSA 実写はスラブ越しで
  自然発色するため、同じカードが別絵柄に見えた。

  不一致台帳18件の実測では 17件が本物の variant 欠落。誤検出は1件 (5.6%)。
  頻度は低いが、当たった1件は自動では絶対に消えない。
"""
from __future__ import annotations

import os
import sys

HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HQ, "tools"))

import post_psa_review as P                                     # noqa: E402

# 実データ (catalog pokemon_tcg S10b-055)
EEVEE = {"name_en": "Radiant Eevee",
         "set_name": "拡張パック「Pokémon GO」",
         "set_name_official": "強化拡張パック「Pokémon GO」",
         "set_name_ebay": "S10b: Pokémon GO",
         "card_number_text": "055/071"}


class TestIdentityMatches:
    def test_全部一致なら人の見間違いとみなす(self):
        psa = {"subject": "RADIANT EEVEE", "card_number": "055",
               "brand": "POKEMON GO JAPANESE"}
        assert P.identity_matches(psa, EEVEE) is True

    def test_アクセントの差で外さない(self):
        """★Pokemon(PSA) と Pokémon(catalog)。落とさないと一致するはずが外れる."""
        assert P._ident_norm("Pokémon GO") == P._ident_norm("POKEMON GO")

    def test_名前に修飾語が付いていたら本物の欠落(self):
        psa = {"subject": "RADIANT EEVEE ALTERNATE ART", "card_number": "055",
               "brand": "POKEMON GO JAPANESE"}
        assert P.identity_matches(psa, EEVEE) is False

    def test_番号が違えば本物の欠落(self):
        psa = {"subject": "RADIANT EEVEE", "card_number": "056",
               "brand": "POKEMON GO JAPANESE"}
        assert P.identity_matches(psa, EEVEE) is False

    def test_セットが違えば本物の欠落(self):
        """台帳18件のうち17件はこちら (brand が別セットを指す = 再録)."""
        psa = {"subject": "RADIANT EEVEE", "card_number": "055",
               "brand": "3RD ANNIVERSARY SET"}
        assert P.identity_matches(psa, EEVEE) is False

    def test_値が欠けていたら一致とみなさない(self):
        """fail-closed: 判定材料が無いのに『見間違い』に倒すと本物を捨てる."""
        for miss in ("subject", "card_number", "brand"):
            psa = {"subject": "RADIANT EEVEE", "card_number": "055",
                   "brand": "POKEMON GO JAPANESE"}
            psa[miss] = ""
            assert P.identity_matches(psa, EEVEE) is False, miss


class TestRoute:
    def test_全一致なら依頼に流さない(self):
        """★このコードが無いと、閉じられない依頼が永久に残る."""
        import inspect
        src = inspect.getsource(P._route_none_to_catalog) \
            if hasattr(P, "_route_none_to_catalog") else inspect.getsource(P)
        assert "identity_matches" in src
        assert "catalog依頼にしない" in src

    def test_catalogを引けなければ従来どおり流す(self):
        """DB が引けない時に『見間違い』へ倒すと、本物の欠落を見落とす."""
        assert P.catalog_identity("pokemon_tcg", "") is None
        assert P.catalog_identity("pokemon_tcg", "無") is None
        assert P.catalog_identity("pokemon_tcg", "ZZZ-999") is None
