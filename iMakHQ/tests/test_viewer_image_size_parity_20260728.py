"""目視HTMLで「現物」と「仕入候補」の画像表示サイズを揃える (2026-07-28 ユーザー指示).

候補が現物より小さいと、変種の違い(★の有無・パラレル・番号)が見分けられず、
目視確証の精度がサイズで頭打ちになる。4つのビューア全部で同寸にする。

サイズは CSS 文字列に直書きなので、片方だけ変更されたら落ちるようにここで固定する。
"""
import os
import re
import sys

TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
sys.path.insert(0, TOOLS)


def _src(name):
    return open(os.path.join(TOOLS, name), encoding="utf-8").read()


def _px(pattern, text):
    m = re.search(pattern, text)
    assert m, f"CSS が見つからない: {pattern}"
    return int(m.group(1))


def test_psa_confirm_candidate_matches_reference():
    """PSA 確証UI: 現物 .col.psa img と 候補 .cand img が同寸。"""
    s = _src("psa_resource_confirm.py")
    ref_w = _px(r"\.col\.psa img\{width:(\d+)px", s)
    ref_h = _px(r"\.col\.psa img\{width:\d+px;height:(\d+)px", s)
    cand_w = _px(r"\.cand img\{width:(\d+)px", s)
    cand_h = _px(r"\.cand img\{width:\d+px;height:(\d+)px", s)
    assert (cand_w, cand_h) == (ref_w, ref_h)


def test_psa_confirm_candidate_is_not_cropped():
    """object-fit:cover は端を切り落とす = 番号や★が隠れる。contain であること。"""
    s = _src("psa_resource_confirm.py")
    m = re.search(r"\.cand img\{[^}]*\}", s)
    assert "object-fit:contain" in m.group(0)
    assert "cover" not in m.group(0)


def test_ichibankuji_candidate_matches_reference():
    s = _src("ichibankuji_restock.py")
    ref = _px(r"\.ref img,\.ref \.noimg\{max-width:(\d+)px", s)
    cand = _px(r"\.cand img\{max-width:(\d+)px", s)
    assert cand == ref


def test_psa_resource_html_candidate_matches_reference():
    s = _src("psa_resource_html.py")
    ref = _px(r"\.ref img\{max-width:(\d+)px", s)
    cand = _px(r"\.cand img\{max-width:(\d+)px", s)
    assert cand == ref


def test_post_psa_review_candidate_matches_reference():
    """現物 .confirm img(max-width) と 候補 .cand img(max-height) を同値に。"""
    s = _src("post_psa_review.py")
    ref = _px(r"\.confirm img\{max-width:(\d+)px", s)
    cand = _px(r"\.cand img\{[^}]*max-height:(\d+)px", s)
    assert cand == ref


def test_post_psa_don_check_candidate_matches_reference():
    s = _src("post_psa_don_check.py")
    ref = _px(r"\.cert-image\{max-width:(\d+)px", s)
    cand = _px(r"\.cand img\{[^}]*max-height:(\d+)px", s)
    assert cand == ref
