"""tests/test_psa_grade_gate - PSA10 以外を通さない.

2026-08-18 user 指摘「PSA9 や BGS9.5、ARS、CCG が混じっているね」。
cert が読めなかった出品を グレードを見ずに入れていたのが原因。
メルカリ検索は説明文にも当たるので、 タイトルに PSA10 が無い出品も返ってくる。
"""
from __future__ import annotations

import pytest

from scrapers.psa_grade_gate import looks_like_psa10

pytestmark = pytest.mark.offline


@pytest.mark.parametrize("title", [
    "PSA10 パルデアウパー AR SV1a 085/073 ポケモンカード",
    "【PSA10】ミミッキュ AR 341/190 シャイニートレジャーex",
    "ラブトロス AR SV5a クリムゾンヘイズ 074/066　PSA10",
    "ゲンガー psa10 S4a シャイニースターV 071/190",
    "【 PSA 10 】【送料無料】 パルデアの学生 SR SV4a 345/190",
])
def test_psa10_variants_pass(title):
    assert looks_like_psa10(title=title)


@pytest.mark.parametrize("title", [
    "【最安値】ピカチュウ CHR ダークファンタズマ 073/071 PSA9",
    "リザードン BGS 9.5 GEM MINT",
    "ピカチュウ ARS10 鑑定品",
    "ナミ CCG10 ワンピースカード",
    "ルフィ SGC 10",
    "PSA 8 ミュウツー 旧裏",
])
def test_other_graders_and_lower_grades_are_rejected(title):
    assert not looks_like_psa10(title=title)


def test_no_grading_mention_is_rejected():
    """鑑定の記載が無い = 生カードの可能性。 確証が無いので通さない."""
    assert not looks_like_psa10(title="ピカチュウ CHR S10a ダークファンタズマ 073/071")
    assert not looks_like_psa10(title="キハダ SAR SV1a トリプレットビート 099/073")


def test_label_grade_is_preferred_when_read():
    """Vision がラベルを読めていれば それを使う (タイトルの表記に依存しない)."""
    assert looks_like_psa10(title="ピカチュウ CHR 073/071",
                            label="2022 POKEMON JAPANESE S10A",
                            grade="GEM MT 10")
    assert not looks_like_psa10(title="【PSA10】ピカチュウ", grade="MINT 9")


def test_other_grader_wins_over_psa10_text():
    """「PSA10」と書いてあっても BGS が混じっていたら通さない (fail-closed)."""
    assert not looks_like_psa10(title="PSA10級 BGS 9.5 リザードン")


def test_card_number_ending_in_10_is_not_a_grade():
    assert not looks_like_psa10(title="ルフィ ST04-10 パラレル")
