# -*- coding: utf-8 -*-
"""PSA のページは **日本語**で読みに行っている (2026-08-23)。

## 何が起きていたか
8/23 朝に「グレードは PSA のページから読む」を入れた時、拾う見出しを英語
(`Item Grade` / `Variety/Pedigree` / `Label Type`) で書いていた。ところが出品くんが
実際に開くのは `https://www.psacard.com/ja-JP/cert/<cert>/psa` = **日本語ページ**で、
見出しは「グレード」「バラエティ」「ラベルタイプ」。**一度も一致していなかった。**

実測: 保存済 1,203件すべて Grade 無し。その場で取り直しても空のままだった。
午後に「PSA10のみ出品」を規定にした時、これが残っていると **全件が
「グレードを確かめられない」で出品ゼロ**になるところだった。

## このテストが守るもの
下の fixture は 2026-08-23 に実機で取得した **本物のページ本文**
(cert158363091 / Boa Hancock PRB01)。推測で書いた文字列ではない。
日本語・英語どちらのページでも同じ値が取れること。
"""
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_TCG = os.path.join(_ROOT, "iMakTCG")
if _TCG not in sys.path:
    sys.path.insert(0, _TCG)
_FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


@pytest.fixture(scope="module")
def mod():
    import psa_to_csv
    return psa_to_csv


def _body(lang):
    with open(os.path.join(_FIX, f"psa_cert_page_{lang}_158363091.txt"),
              encoding="utf-8") as f:
        return f.read()


@pytest.mark.parametrize("lang", ["ja", "en"])
def test_grade_is_read_from_the_real_page(mod, lang):
    d = mod.parse_psa_page(_body(lang))
    assert d.get("Grade") == "GEM MT 10", f"{lang} ページからグレードが取れていない"
    assert mod.grade_number(d["Grade"]) == "10"
    assert mod.is_psa10_confirmed("PSA 10 何か", mod.grade_number(d["Grade"])) is True


@pytest.mark.parametrize("lang", ["ja", "en"])
def test_other_fields_from_the_real_page(mod, lang):
    d = mod.parse_psa_page(_body(lang))
    assert d.get("Variety") == "ALTERNATE ART"
    assert d.get("Population") == "836"
    assert d.get("PopHigher") == "0"
    assert d.get("LabelType")           # 表記は言語で変わるので、取れていることだけ見る


def test_population_labels_are_not_confused(mod):
    """「グレーディング枚数」と「より高評価のグレーディング枚数」を取り違えない。"""
    d = mod.parse_psa_page(_body("ja"))
    assert d["Population"] == "836" and d["PopHigher"] == "0"


def test_japanese_labels_are_registered(mod):
    """出品くんが開く URL は日本語。日本語の見出しが表に無いと永久に空になる。"""
    src = open(os.path.join(_TCG, "psa_to_csv.py"), encoding="utf-8").read()
    assert "/ja-JP/cert/" in src, "見に行く URL が変わったら、この表も見直すこと"
    for label in ("グレード", "バラエティ", "ラベルタイプ"):
        assert label in mod._PSA_PAGE_FIELDS, f"日本語の見出し {label} が表に無い"
