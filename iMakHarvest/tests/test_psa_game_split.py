"""tests/test_psa_game_split - 中間スプシをゲーム毎のタブに分ける.

2026-08-18 user 指示。 判定は「その出品から取れた事実」 (Vision のラベル / 出品タイトル /
カード番号) だけを使い、 判らない物は捨てずに `_other` へ入れる。
"""
from __future__ import annotations

import pytest

from run_harvest_mercari_psa10 import group_by_game, item_game
from scrapers.psa_game import detect_item_game, tab_label

pytestmark = pytest.mark.offline


def _c(title="", label="", card_number="", cert="1"):
    return {"url": f"u{title}{label}", "title": title,
            "vision": {"label": label, "card_number": card_number, "cert": cert}}


def test_detect_from_label():
    assert detect_item_game(label="2025 ONE PIECE OP13 JP JEWELRY BONNEY") == "onepiece"
    assert detect_item_game(label="2023 POKEMON JAPANESE SV4a #205") == "pokemon"


def test_detect_from_japanese_title():
    assert detect_item_game(title="PSA10 ワンピースカード ルフィ パラレル") == "onepiece"
    assert detect_item_game(title="PSA10 ポケカ ピカチュウ") == "pokemon"
    assert detect_item_game(title="PSA10 ドラゴンボール フュージョンワールド 悟空") == "dragonball"
    assert detect_item_game(title="PSA10 ガンダムカードゲーム ハマーン") == "gundam"


def test_detect_from_set_code_when_game_name_absent():
    """ラベルにゲーム名が出ない時は 弾コードで判る."""
    assert detect_item_game(card_number="OP13-004") == "onepiece"
    assert detect_item_game(card_number="GD02-072") == "gundam"
    assert detect_item_game(card_number="FB01-005") == "dragonball"


def test_unknown_goes_to_other():
    assert detect_item_game(title="PSA10 遊戯王 ブラックマジシャン") == "other"
    assert detect_item_game() == "other"


def test_tab_label():
    assert tab_label("psa10", "onepiece") == "psa10_onepiece"
    assert tab_label("psa10", "") == "psa10_other"


def test_group_by_game_splits_kept_and_unreadable():
    kept = [_c(title="PSA10 ワンピース ルフィ"), _c(label="2024 POKEMON SV5a")]
    unreadable = [_c(title="PSA10 ガンダム ハマーン", cert="")]
    got = group_by_game(kept, unreadable)
    assert set(got) == {"onepiece", "pokemon", "gundam"}
    assert len(got["onepiece"][0]) == 1 and got["onepiece"][1] == []
    assert got["gundam"][0] == [] and len(got["gundam"][1]) == 1


def test_group_by_game_never_drops_items():
    items = [_c(title="PSA10 遊戯王"), _c(title="PSA10 ワンピース")]
    got = group_by_game(items, [])
    assert sum(len(k) for k, _ in got.values()) == 2
    assert "other" in got


def test_item_game_prefers_label_over_missing_title():
    assert item_game(_c(title="", label="2025 ONE PIECE OP13")) == "onepiece"


# --------------------------------------------------------------------------
# 実データで落ちたケース (2026-08-18 の 230 行で実測して潰した分)
# --------------------------------------------------------------------------
def test_set_code_in_brackets_is_found():
    """"ナミ SR-P [OP08-106]" の括弧付き弾コードを拾う."""
    assert detect_item_game(title="ナミ SR-P [OP08-106](「二つの伝説」) PSA10") == "onepiece"
    assert detect_item_game(title="【PSA10】ルフィ&エース リーダーパラレルST30-001") == "onepiece"


def test_psa10_token_does_not_stop_detection():
    """先頭の "PSA10" を弾コードと誤認して判定を諦めない."""
    assert detect_item_game(title="PSA10 ナミ OP08-106") == "onepiece"


def test_japanese_name_longest_match_wins():
    """「ハンコック」の中の「コック」(別ゲームのカード名) に負けない."""
    ja = {"ボア・ハンコック": "onepiece", "コック": "pokemon"}
    got = detect_item_game(title="【PSA10】ボア・ハンコック プロモ UC パラレル",
                           ja_name_games=ja)
    assert got == "onepiece"


def test_japanese_name_ambiguous_same_length_is_other():
    ja = {"リオレイア": "pokemon", "リオレウス": "gundam"}
    assert detect_item_game(title="PSA10 リオレイア リオレウス", ja_name_games=ja) == "other"
