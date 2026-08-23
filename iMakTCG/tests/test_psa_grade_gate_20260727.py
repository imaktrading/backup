# -*- coding: utf-8 -*-
"""★PSA10 のみ出品する (2026-07-27 実事故 → 2026-08-23 にユーザーが規定として確定)。

## 事故 (2026-07-27)
cert152687772 Dragon Ball E-60 Energy Marker は **実物 PSA 9**(ラベル "MINT 9") なのに、
CSV は `PSA 10 Dragon Ball Manga Booster 01 #E-60 Energy Marker 2025` / CustomLabel
`PSA10-152687772` / `C:Grade=10` で生成され、**$494.98 で入稿寸前**だった。

## 真因: パイプライン全体が PSA10 限定運用の前提
- `build_title()` は `prefix = "PSA 10"` 固定 / `build_row` は `C:Grade = "10"` 固定
- 新コア override が その C:Grade を読んでタイトルを `PSA 10 ...` に再生成
  → **Claude が画像から正しく出していた `PSA 9 ...` が上書きされた**
- 市場ゲートも "PSA 10 ..." で検索 → PSA10 相場を引き **GO(利益71%)** と誤判定

## 方針の変更 (2026-08-23 ユーザー規定「PSA10のみの出品と規定したらいい」)
**旧**: 10 でないと読めた時だけ止める。読めなければ通す (fail-open)。
**新**: **PSA10 だと確かめられた時だけ出す。** 読めなければ出さない。

旧は「グレードが読めない個体」が素通りしていた。実測 2026-08-23: その日出した9件は
全て保存済データからの読み出しで、**グレードを一度も確かめていなかった**。
タイトルも C:Grade も相場も "10" 固定なので、それは誤表示のまま出るということ。

現物由来 (PSA ページの Item Grade / ラベル画像) が '10' と言った時だけ確定とする。
タイトルの `PSA 10` は **こちらが組んだ文字列**なので、単独では根拠にしない。
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from psa_to_csv import (detected_grade_from_title, is_psa10_confirmed,  # noqa: E402
                        is_psa10_or_unknown, supplier_grade_hint, non_psa10_certs)


# --------------------------------------------------------- 現物由来のグレード
def test_confirmed_only_when_real_grade_says_ten():
    """★本命: 現物のグレードが 10 と言った時だけ出す。"""
    assert is_psa10_confirmed("PSA 10 Pokemon ...", psa_grade="10") is True
    assert is_psa10_confirmed("PSA 10 Dragon Ball ... #E-60", psa_grade="9") is False


@pytest.mark.parametrize("g", ["", None, "  "])
def test_unreadable_grade_is_not_listed(g):
    """★2026-08-23 の反転: 読めなければ **出さない**。

    タイトルが "PSA 10" でも通さない。そのタイトルは自分で組んだものなので根拠にならない。
    """
    assert is_psa10_confirmed("PSA 10 Pokemon ...", psa_grade=g) is False


def test_title_alone_is_not_evidence():
    assert is_psa10_confirmed("PSA 10 One Piece #OP08-058 Charlotte Pudding Alt Art") is False


def test_title_saying_not_ten_blocks_even_if_grade_says_ten():
    """食い違ったら出さない (どちらかが 10 以外と言えば止める)。"""
    assert is_psa10_confirmed("PSA 9 Pokemon ...", psa_grade="10") is False


def test_other_low_grades_blocked():
    for g in ("8", "7", "1", "9.5"):
        assert is_psa10_confirmed("PSA 10 x", psa_grade=g) is False, g


def test_old_gate_is_gone_and_says_so():
    """旧判定は残骸として残さない。呼ばれたら黙って旧挙動に戻らず、止まって理由を言う。"""
    with pytest.raises(RuntimeError) as e:
        is_psa10_or_unknown("PSA 10 x", psa_grade=None)
    assert "is_psa10_confirmed" in str(e.value)


# --------------------------------------------------------- 仕入元タイトル (入口)
def test_supplier_title_hint():
    """★本命2: 仕入元タイトルの PSA9 表記(実際に誤出品6件を発見した信号)。"""
    assert supplier_grade_hint("【PSA9・ワンオーナー】バギー 金ドン スーパーパラレルドン") == "9"
    assert supplier_grade_hint("2023 ONE PIECE モンキー・D・ルフィ #033　PSA9") == "9"
    assert supplier_grade_hint("ルカリオ＆メルメタルGX UR PSA9") == "9"
    assert supplier_grade_hint("【PSA10・ワンオーナー】シャンクス 金ドン") is None      # 10 は拾わない
    assert supplier_grade_hint("PSA 10 ワンピース") is None
    assert supplier_grade_hint("") is None


def test_other_grading_companies_are_dropped_at_the_door():
    """★2026-08-23: PSA 以外の鑑定会社は入口で落とす。

    番号だけ入力されると PSA のサイトを引いてしまい、たまたま同じ番号の PSA cert が
    実在すると **別のカードとして出品**される (いちばん危険な型)。
    BGS/CGC は数字グレードを併記するので `PSA n` の正規表現では拾えない。
    """
    assert supplier_grade_hint("【CGC10】ピカチュウ") == "CGC"
    assert supplier_grade_hint("BGS 9.5 Charizard") == "BGS"
    assert supplier_grade_hint("SGC 10 Mickey") == "SGC"
    assert supplier_grade_hint("ARS10 リザードン") == "ARS"


def test_other_grader_word_does_not_drop_a_real_psa10():
    """付属品で他社名が出るだけの PSA10 を捨てない (1枠を無駄にしない)。"""
    assert supplier_grade_hint("PSA10 CGCカードローダー付き") is None
    assert supplier_grade_hint("PSA 10 SGCスリーブ同梱 ピカチュウ") is None


def test_plain_title_is_not_flagged():
    assert supplier_grade_hint("ピカチュウ 美品 即購入可") is None
    assert supplier_grade_hint("ポケモンカード(グレード表記なし)") is None


def test_non_psa10_certs_filters_targets():
    m = {"152976738": "【PSA9・ワンオーナー】バギー 金ドン",
         "158715772": "【PSA10】シャンクス ALT",
         "160000001": "【CGC10】ピカチュウ",
         "111": "ポケモンカード(グレード表記なし)"}
    assert non_psa10_certs(m) == {"152976738": "9", "160000001": "CGC"}


def test_detect_grade():
    assert detected_grade_from_title("PSA 9 Dragon Ball SCG Manga Booster 01 #E-60 Energy Marker Card") == "9"
    assert detected_grade_from_title("PSA 10 Pokemon Japanese Crimson Haze #083/066 Greninja ex") == "10"
    assert detected_grade_from_title("psa 8 something") == "8"
    assert detected_grade_from_title("Pokemon Card without grade") is None
    assert detected_grade_from_title("") is None
    assert detected_grade_from_title(None) is None
