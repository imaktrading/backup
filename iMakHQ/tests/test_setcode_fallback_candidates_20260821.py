# -*- coding: utf-8 -*-
"""セット記号を読めない時に目視の候補がゼロになっていた (2026-08-21)。

回答書: 2026-08-20_hq_act_proposals_ebay_norm_and_act_lock_response.md (C)

固定する挙動:
  C-1 セット記号を取れなくても打ち切らない。
      「name_en が Subject と完全一致 かつ 番号が一致」する行を候補に出す。
  C-2 Pokemon の **英字だけの set_code** (`CLL-` `CLK-` `CLF-` `MBD-`) を読む。
      ただし **語頭 (JAPANESE の直後) だけ**。'SKY-SPLITTING' / 'JET-BLACK' を
      set_code と誤読すると `LIKE 'SKY-%'` が0件になり、番号一致の候補まで消える。
  共通 候補は候補のまま。弱い当てずっぽうを expected に昇格させない。
"""
from __future__ import annotations

import os
import sys

import pytest

_TOOLS = r"C:\dev\iMak\iMakHQ\tools"
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import post_psa_review as R  # noqa: E402

# 実 catalog DB を読む test (書かない)。DB が無い環境では skip。
_HAS_DB = os.path.exists(str(R.CATALOG_DB))
_needs_db = pytest.mark.skipif(not _HAS_DB, reason="catalog DB が無い環境")

FILM_RED = "ONE PIECE JAPANESE FILM RED: ENCORE PACK"
CLL = "POKEMON JAPANESE CLL-TRADING CARD GAME CLASSIC CHARIZARD & HO-OH EX DECK"


# --- C-2: set_code 抽出 (純関数・DB 不要) ---------------------------------

def test_pokemon_reads_letters_only_set_code():
    """`CLL-` `CLK-` `CLF-` `MBD-` を読む (2026-08-21 実測で PSA cache に在る4種)。"""
    assert R._extract_set_code(CLL, "pokemon_tcg") == "CLL"
    assert R._extract_set_code(
        "POKEMON JAPANESE CLK-TRADING CARD GAME CLASSIC BLASTOISE & SUICUNE EX DECK",
        "pokemon_tcg") == "CLK"
    assert R._extract_set_code(
        "POKEMON JAPANESE MBD-MEGA STARTER SET MEGA DIANCIE EX",
        "pokemon_tcg") == "MBD"


def test_pokemon_does_not_misread_set_name_words():
    """セット名の途中のハイフン語を set_code にしない (誤読は候補を減らす = 改悪)。"""
    for brand in (
        "POKEMON JAPANESE SUN & MOON SKY-SPLITTING CHARISMA",
        "POKEMON JAPANESE SWORD & SHIELD JET-BLACK SPIRIT",
    ):
        assert R._extract_set_code(brand, "pokemon_tcg") is None, brand


def test_numeric_set_code_still_wins():
    """英数字混在の既存 code を3文字規則に食わせない。"""
    assert R._extract_set_code(
        "POKEMON JAPANESE SV8A-TERASTAL FESTIVAL EX", "pokemon_tcg") == "SV8A"


def test_letters_only_code_is_not_promoted_to_expected():
    """候補の絞込にだけ使う。`CLL-002` を期待値に昇格させない。"""
    assert R.synthesized_expected("CLL", "002") is None
    assert R.synthesized_expected("MBD", "014") is None
    assert R.synthesized_expected("ST11", "004") == "ST11-004"


# --- 候補が0件にならない (回答書の追加要求) -------------------------------

@_needs_db
def test_film_red_candidates_are_not_empty():
    """set_code を取れない brand でも候補が出る。ST11-004 系が並ぶこと。"""
    sc = R._extract_set_code(FILM_RED, "one_piece_tcg")
    assert sc is None                      # ここは取れないままで正しい
    pids = [p for p, _ in R._get_candidates(
        "one_piece_tcg", sc, "004", brand=FILM_RED, subject="NEW GENESIS")]
    assert pids, "候補ゼロ"
    assert [p for p in pids if p.startswith("ST11-004")], pids[:10]


@_needs_db
def test_cll_candidates_are_not_empty():
    """CLL を読めたので CLL-002 (Charmeleon) が候補に出る。"""
    sc = R._extract_set_code(CLL, "pokemon_tcg")
    pids = [p for p, _ in R._get_candidates(
        "pokemon_tcg", sc, "002", brand=CLL, subject="CHARMELEON")]
    assert "CLL-002" in pids, pids[:10]


@_needs_db
def test_exact_name_plus_number_is_the_only_path_when_subject_has_no_tokens():
    """C-1 の本体。Subject が短くてキャラ名検索が効かない時、ここだけが候補を出す。

    実測 2026-08-21: Subject 'A.O.' はトークンが1つも取れず (3文字未満)、
    キャラ名検索が空回りして **無関係な30件** (最終 safety net) が並んでいた。
    """
    src = open(os.path.join(_TOOLS, "post_psa_review.py"), encoding="utf-8").read()
    guard = "if not rows and not set_code and card_number and subject:"
    assert guard in src, "優先度2b が無い"

    pids = [p for p, _ in R._get_candidates(
        "one_piece_tcg", None, "014", brand=FILM_RED, subject="A.O.")]
    assert pids, "候補ゼロ"
    assert all(p.startswith("ST22-014") for p in pids), pids[:10]


# --- 弱い当てずっぽうの扱いは変えない -------------------------------------

def test_weak_promo_guess_unchanged():
    weak = "    🎯 iMakCatalog hit (promo fallback) OP07-118 score=10"
    strong = "    🎯 iMakCatalog hit (promo fallback) OP07-118 score=300"
    assert R.weak_promo_guess(weak) is True
    assert R.weak_promo_guess(strong) is False
    assert R.weak_promo_guess("") is False
