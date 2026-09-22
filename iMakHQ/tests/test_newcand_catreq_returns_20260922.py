"""新規候補: 「カタログに無い→追加依頼」は、カタログに版が入ったら また候補に出す (2026-09-22)。
NG に入れて永久に外していたので、カタログが足しても戻らなかった。"""
import os

SRC = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools",
                        "newcand_confirm.py"), encoding="utf-8").read()


def test_catreq_rows_are_not_permanently_done():
    assert "done |= {_nurl(r[0]) for r in _ng_all} - catreq_urls" in SRC


def test_returns_only_when_card_number_hits_catalog():
    assert "in catreq_urls and not (card_no and catalog_variants(card_no))" in SRC


def test_request_rows_carry_the_marker():
    assert 'CATREQ_REASON + " → 追加依頼を起票"' in SRC
    assert 'CATREQ_REASON = "カタログ未収録"' in SRC
