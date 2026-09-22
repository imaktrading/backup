"""目視で候補に無い時、「カタログを見る」のカタログIDを入れてその場で候補を出す (2026-09-22)。
ユーザー「対象の作業がある画面全てに入れた方がいいのでは？一生直らないものが、都度直せる」"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
import psa_resource_confirm as P                              # noqa: E402

SRC = lambda n: open(os.path.join(HERE, "..", "tools", n), encoding="utf-8").read()  # noqa: E731


def test_resource_confirm_has_find_box_even_without_candidates():
    h = P.build_confirm_html([{"idx": 3, "title": "t", "card_no": "", "psa_image": "", "candidates": []}])
    assert "findCat(3)" in h and "/api/find" in h


def test_found_option_is_a_selectable_radio_of_same_group():
    h = P.cand_option_html(3, {"key": "XY9-B-018", "image": "", "label": "x"}, checked=True)
    assert "name='pick3'" in h and "value='XY9-B-018'" in h and " checked" in h


def test_psa_review_find_box_is_outside_collapsed_list():
    s = SRC("post_psa_review.py")
    assert s.index("class=findbox") < s.index('class=candidates-toggle')
    assert 'document.getElementById("cands_" + cert).classList.add("show")' in s


def test_newcand_input_says_catalog_id():
    assert "カード番号 / カタログID" in SRC("newcand_confirm.py")
