"""新規目視: 画像の無い候補 (英語版の画像しか無いカタログ行) は出さない (2026-10-05 ユーザー指示)。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import post_psa_review as P  # noqa: E402


def test_drop_no_image():
    cands = [("P-006", "https://example.com/p006.png", "Vジャンプ"),
             ("P-006_dummy", "", "Promotion Card"),
             ("P-006_win_dummy", None, "Promotion Card"),
             ("OP06-068_AC01", r"C:\no\such\file.png", "Admirable Collection vol.1")]
    assert [c[0] for c in P.drop_no_image(cands)] == ["P-006"]


def test_drop_no_image_empty():
    assert P.drop_no_image(None) == [] and P.drop_no_image([]) == []
