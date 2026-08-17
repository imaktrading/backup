"""tests/test_demand_keywords - 需要実証済カードから検索キーワードを作る.

2026-08-18 新設。 ファネル分析の RESTOCK (在庫切れ × 需要あり) から
カード番号を取って検索語にする。 推測で語を作らない (= 番号が取れない行は捨てる) 事を固定する。
"""
from __future__ import annotations

import pytest

from scrapers.demand_keywords import (
    build_keywords_from_rows,
    demand_score,
    detect_game,
    extract_card_number,
    resolve_japanese_name,
)

pytestmark = pytest.mark.offline

# カタログの 英名→和名 表 (実物と同じ形の最小データ)
NAME_MAP = {
    "one_piece_tcg": {"NICO ROBIN": "ニコ・ロビン", "CARROT": "キャロット"},
    "gundam_tcg": {"HAMAN KARN": "ハマーン・カーン",
                   "FREEDOM GUNDAM": "フリーダムガンダム"},
    "pokemon_tcg": {"HO-OH": "ホウオウ", "NATU": "ネイティ"},
    "dragonball_scg": {"SON GOKU": "孫悟空"},
}


def _row(title, watch=0, impr=0, sales90=0):
    return {"title": title, "watch": watch, "impr": impr, "sales90": sales90}


def test_extract_card_number_variants():
    assert extract_card_number("PSA 10 One Piece #OP08-106 Nami") == "OP08-106"
    assert extract_card_number("PSA10 Gundam GD02-072 Promo") == "GD02-072"
    assert extract_card_number("PSA 10 SB02 001 Luffy") == "SB02-001"


def test_extract_card_number_none_when_absent():
    """番号が無いタイトルから推測しない (別カードを拾うため)."""
    assert extract_card_number("PSA 10 One Piece Luffy Manga Rare") == ""
    assert extract_card_number("Weiss Schwarz NIKKE #026 RRR") == ""


def test_non_psa_rows_are_ignored():
    rows = [_row("Gundam CCG Edition Beta #GD02-072", watch=9)]
    assert build_keywords_from_rows(rows) == []


def test_keywords_are_sorted_by_demand():
    rows = [
        _row("PSA 10 One Piece #OP01-001", watch=1),
        _row("PSA 10 One Piece #OP02-002", sales90=1),   # 実売が最優先
        _row("PSA 10 One Piece #OP03-003", watch=5),
    ]
    assert build_keywords_from_rows(rows) == [
        "PSA10 OP02-002", "PSA10 OP03-003", "PSA10 OP01-001",
    ]


def test_same_card_is_not_duplicated():
    rows = [_row("PSA 10 #OP08-106 A", watch=1), _row("PSA 10 OP08-106 B", watch=9)]
    assert build_keywords_from_rows(rows) == ["PSA10 OP08-106"]


def test_limit_takes_top_n():
    rows = [_row(f"PSA 10 #OP0{i}-00{i}", watch=i) for i in range(1, 5)]
    assert build_keywords_from_rows(rows, limit=2) == ["PSA10 OP04-004", "PSA10 OP03-003"]


def test_demand_score_handles_dirty_numbers():
    assert demand_score({"watch": "1,000", "impr": "", "sales90": None}) == 10000.0


# --------------------------------------------------------------------------
# 番号表記のゆれ (ポケモン分数 / プロモ) と カタログ引き当ての和名
# --------------------------------------------------------------------------
def test_pokemon_fraction_number():
    assert extract_card_number("PSA 10 Pokemon Paldea Evolved #077/071 Baxcalibur") == "077/071"
    assert extract_card_number("PSA 10 Pokemon Promo #232/S-P Piplup") == "232/S-P"


def test_promo_number():
    assert extract_card_number("One Piece Promo Pack EX Vol.2 P-066 Boa Hancock PSA 10") == "P-066"


def test_detect_game_covers_four_games():
    assert detect_game("PSA 10 One Piece TCG Nami") == "one_piece_tcg"
    assert detect_game("PSA 10 Pokemon Eevee") == "pokemon_tcg"
    assert detect_game("PSA 10 Dragon Ball Fusion World Goku") == "dragonball_scg"
    assert detect_game("PSA 10 Gundam Card Game Haman Karn") == "gundam_tcg"
    assert detect_game("Weiss Schwarz NIKKE Ludmilla PSA 10") == ""


def test_resolve_japanese_name_uses_catalog():
    t = "One Piece Card Game Nico Robin Promotion Card Set 3 #008 PSA 10"
    assert resolve_japanese_name(t, NAME_MAP) == "ニコ・ロビン"


def test_resolve_japanese_name_requires_word_boundary():
    """SIGNATURE の中の NATU を拾って別カード (ネイティ) に化けない."""
    t = "Weiss Schwarz NIKKE Ludmilla Winter Owner #063 SP Signature PSA 10"
    assert resolve_japanese_name(t, NAME_MAP) == ""
    t2 = "PSA 10 Pokemon Promo Signature Card"  # ゲームは判るが NATU は単語でない
    assert resolve_japanese_name(t2, NAME_MAP) == ""


def test_resolve_japanese_name_prefers_longest_match():
    t = "Gundam Card Game Japanese Freedom Gundam #008 PSA 10"
    assert resolve_japanese_name(t, NAME_MAP) == "フリーダムガンダム"


def test_unknown_game_is_not_converted():
    rows = [_row("Weiss Schwarz NIKKE Sea You Again #026 RRR PSA 10", watch=9)]
    assert build_keywords_from_rows(rows, name_map=NAME_MAP) == []


def test_number_wins_over_name():
    rows = [_row("PSA 10 One Piece #OP08-106 Nico Robin", watch=1)]
    assert build_keywords_from_rows(rows, name_map=NAME_MAP) == ["PSA10 OP08-106"]


def test_name_used_when_no_number():
    rows = [_row("One Piece Card Game Nico Robin Promotion Set PSA 10", watch=1)]
    assert build_keywords_from_rows(rows, name_map=NAME_MAP) == ["PSA10 ニコ・ロビン"]
