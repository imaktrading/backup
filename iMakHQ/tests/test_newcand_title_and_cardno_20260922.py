"""新規候補: タイトルが無い/番号が読めない候補を減らす (2026-09-22)。"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
import newcand_confirm as N                                    # noqa: E402
import hoju_url_from_dupes as H                                # noqa: E402


def test_op_promo_and_spaced_numbers():
    assert N.extract_card_no("PSA10 モンキー・D・ルフィ P-006 Vジャンプ") == "P-006"
    assert N.extract_card_no("Sabo P-SPC [P-105](Booster") == "P-105"
    assert N.extract_card_no("ワンピースカード st30 001") == "ST30-001"
    assert N.extract_card_no("PSA10 001 ピカチュウ") == ""
    assert N.extract_card_no("SV-P-106") == ""
    assert N.extract_card_no("【PSA10】OP05-002") == "OP05-002"


def test_title_from_mercari_detail():
    assert H.title_from_detail('<meta property="og:title" content="ルフィ P-006 by メルカリ">') == "ルフィ P-006"
    assert H.title_from_detail("<title>ピカチュウ 025/165 - メルカリ</title>") == "ピカチュウ 025/165"
    assert H.title_from_detail("<title>メルカリ</title>") == ""


def test_fill_titles_rereads_number_but_keeps_typed():
    it = {"url": "u1", "title": "", "card_no": "", "variants": [], "dups": [
        {"url": "u2", "title": "", "card_no": "X", "no_from_typed": True}]}
    N.catalog_candidates = lambda t, no: [{"pid": no}]
    assert N.fill_titles([it], {"u1": "ルフィ P-006", "u2": "ルフィ P-106"}) == 2
    assert it["card_no"] == "P-006" and it["variants"] == [{"pid": "P-006"}]
    assert it["dups"][0]["card_no"] == "X"


def test_snkrdunk_title_from_html():
    h = ('<meta property="og:title" content="【PSA10】サボ P-SPC [P-105](ブースターパック) '
         '1枚のシングルトレカ通販｜スニダン">')
    assert N.snkrdunk_title_from_html(h) == "【PSA10】サボ P-SPC [P-105](ブースターパック)"
    assert N.snkrdunk_title_from_html("<title>404 Not Found | スニーカーダンク</title>") == ""
