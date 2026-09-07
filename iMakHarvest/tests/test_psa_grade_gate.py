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


# --------------------------------------------------------------------------
# 2026-08-19 是正: CGC (鑑定会社) と CCG (Collectible Card Game) の取り違え
# --------------------------------------------------------------------------
@pytest.mark.parametrize("title", [
    "CGC10 PSA10 相当　S-スネーク R-P 受け継がれる意志",
    "【CGC10 psa10相当】ラブーン SR-P [EB01-048]",
    "PSA10 ボア・ハンコック OP13-051 R パラレル CGC10",
    "CGC 10 PSA10相当 チョッパー C ST01-006 a510",
    "ピカチュウ ARS10 鑑定品",
])
def test_cgc_and_ars_are_rejected_even_with_psa10_text(title):
    """"CGC10 PSA10相当" のような併記出品を通さない。  は数字が続くと立たない."""
    assert not looks_like_psa10(title=title)


def test_ccg_is_not_a_grader():
    """"Gundam CCG Edition Beta" は ガンダムの正規タイトル (Collectible Card Game)."""
    assert looks_like_psa10(
        title="Gundam CCG Edition Beta Promos #006 EX BASE PSA 10 GEM MT")


def test_letters_around_do_not_false_match():
    """STARS の ARS 等に当たらない."""
    assert looks_like_psa10(title="PSA10 STARS ルフィ OP01-024")


# --------------------------------------------------------------------------
# 複数枚のまとめ売りは採らない (2026-09-05 user 確定)
# --------------------------------------------------------------------------
@pytest.mark.parametrize("title,bundle", [
    ("ポケモンカード PSA10 リザードンex SR", False),
    ("PSA10 ミュウツー SR 美品 1枚", False),
    ("PSA10 ポケカ 3枚セット", True),
    ("PSA10 まとめ売り ポケモンカード", True),
    ("PSA10 ピカチュウ 2枚", True),
    ("ポケカ PSA10 コンプ", True),
    ("PSA10 リーリエ PSA10 マリィ", True),
])
def test_is_bundle(title, bundle):
    """PSA10 は現物1枚に鑑定番号1つ。まとめ売りは出品の材料にならない."""
    from scrapers.psa_grade_gate import is_bundle
    assert is_bundle(title) is bundle


def test_price_cap_is_the_default():
    """★7万円上限は既定 (2026-09-05 user 確定)。 付け忘れても効くようにする."""
    import argparse
    import run_harvest_mercari_psa10 as R
    ap = argparse.ArgumentParser()
    # main() と同じ既定値を持つことだけ確認する (実行はしない)
    src = open(R.__file__, encoding="utf-8").read()
    assert '"--price-max", type=int, default=70000' in src


def test_n_column_is_never_filled():
    """★仕入値は F列だけ。N (HIGH の ARRAYFORMULA 列) には書かない (2026-09-08 user 確定)."""
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1]
           / "run_harvest_mercari_psa10.py").read_text(encoding="utf-8")
    assert '"fill_high_columns": False' in src
    from sheet_writer_amazon import _build_row
    row = _build_row({"url": "https://jp.mercari.com/item/m1", "title": "t",
                      "price_jpy": "5000", "fill_high_columns": False})
    assert row[13] == ""      # N
