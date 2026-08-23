# -*- coding: utf-8 -*-
"""PSA cert ページから グレード等を読む (2026-08-23)。

なぜ: グレードは Claude にラベル画像を読ませて **推測**していた。ページ本文に
`Item Grade  GEM MT 10` と書いてあるので、そちらを一次情報として使う。
実取得で確認 (cert158363091 / 2026-08-23)。

副次: 本番 (TCG_USE_NEW_GEN=1) はタイトルを新コアが作り直すので、Claude タイトルは
100% 捨てられていた (8/22 の走行で 19/19)。グレードが読めた時は API を呼ばない。

守るもの:
  - ページの5項目 (Grade / Variety / LabelType / Population / PopHigher) を拾う
  - 'GEM MT 10' → '10' / 'MINT 9' → '9' / 読めなければ ''
  - PSA10 以外は出品しない (fail-closed は維持)
  - グレードが読めない時は従来どおり画像判定に落ちる (= 呼び出しを消し切らない)
"""
import importlib.util
import os
import sys

import pytest

_TCG = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "iMakTCG")


if _TCG not in sys.path:                      # psa_to_csv は同ディレクトリの module を import する
    sys.path.insert(0, _TCG)


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location("psa_to_csv_pagefields", os.path.join(_TCG, "psa_to_csv.py"))
    m = importlib.util.module_from_spec(spec)
    sys.modules["psa_to_csv_pagefields"] = m
    spec.loader.exec_module(m)
    return m


# 2026-08-23 に実際のページから取った本文 (抜粋・並び順もそのまま)
REAL_BODY = """Cert #158363091
2024 ONE PIECE JAPANESE PRB01-PREMIUM BOOSTER -ONE PIECE CARD THE BEST- #078 BOA HANCOCK ALTERNATE ART
ITEM GRADE
GEM MT 10
PSA ESTIMATE
$87.00
PSA POPULATION
836
PSA POP HIGHER
0
Item Information
Cert Number
158363091
Item Grade
GEM MT 10
Label Type
W/ FUGITIVE INK TECHNOLOGY
Year
2024
Brand/Title
ONE PIECE JAPANESE PRB01-PREMIUM BOOSTER -ONE PIECE CARD THE BEST-
Subject
BOA HANCOCK
Card Number
078
Variety/Pedigree
ALTERNATE ART"""


def test_reads_five_fields_from_real_page(mod):
    d = mod.parse_psa_page(REAL_BODY)
    assert d["Grade"] == "GEM MT 10"
    assert d["Variety"] == "ALTERNATE ART"      # 版の違い = 同定のキー
    assert d["LabelType"] == "W/ FUGITIVE INK TECHNOLOGY"
    assert d["Population"] == "836" and d["PopHigher"] == "0"


def test_existing_fields_still_parsed(mod):
    d = mod.parse_psa_page(REAL_BODY)
    assert d["CardNumber"] == "078"
    assert "BOA HANCOCK" in d["Subject"]
    assert "ONE PIECE JAPANESE" in d["Brand"]


@pytest.mark.parametrize("raw,want", [
    ("GEM MT 10", "10"), ("MINT 9", "9"), ("NM-MT 8", "8"),
    ("EX-MT 6.5", "6.5"), ("", ""), (None, ""), ("AUTHENTIC", ""),
])
def test_grade_number(mod, raw, want):
    assert mod.grade_number(raw) == want


def test_psa9_is_rejected(mod):
    """★2026-08-23 午後 ユーザー規定「PSA10のみの出品」で **読めない時も出さない**に反転。

    それまでは「読めない = 従来どおり続行」だった。ところがグレードは保存済データに
    入っておらず、その日出した9件は一度も確かめていなかった (= 事実上ノーガード)。
    タイトルも C:Grade も相場も "10" 固定なので、確かめずに出すのは誤表示のまま出すこと。
    """
    assert mod.is_psa10_confirmed("PSA 10 何か", "9") is False
    assert mod.is_psa10_confirmed("PSA 10 何か", "10") is True
    assert mod.is_psa10_confirmed("PSA 10 何か", "") is False   # 読めない = 出さない


def test_missing_labels_do_not_break(mod):
    d = mod.parse_psa_page("Cert #1\nItem Grade")     # 値の行が無い
    assert "Grade" not in d


def test_claude_is_skipped_only_when_grade_is_known(mod):
    src = open(os.path.join(_TCG, "psa_to_csv.py"), encoding="utf-8").read()
    assert 'if os.environ.get("TCG_USE_NEW_GEN") == "1" and _page_grade:' in src, \
        "新コア有効 かつ グレードが読めた時だけ API を省く条件が消えている"
    assert "generate_title_with_claude(" in src, \
        "グレードが読めない時の画像判定 (fail-closed の逃がし口) まで消してはいけない"
