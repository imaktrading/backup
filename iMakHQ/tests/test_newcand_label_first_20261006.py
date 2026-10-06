"""補で「違う」と答えた候補でも、鑑定番号でラベルが分かれば 新規の種の画面でそのカードを最初から選ぶ (2026-10-06)。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import newcand_confirm as N  # noqa: E402


def test_label_card_goes_first_with_mark():
    vs = [{"pid": "A", "category": "c", "image": ""}, {"pid": "B", "category": "c", "image": ""}]
    out = N.label_first(vs, "B")
    assert [v["pid"] for v in out] == ["B", "A"] and out[0]["label"] is True
    assert "data-label='1'" in N.variant_cards_html(out)


def test_label_card_added_when_missing_and_noop_without_label():
    vs = [{"pid": "A", "category": "c", "image": ""}]
    assert [v["pid"] for v in N.label_first(vs, "Z", {"pid": "Z", "category": "c", "image": ""})] == ["Z", "A"]
    assert N.label_first(vs, "") == vs
    assert "DOMContentLoaded" in N._JS and "data-label='1'" in N._JS
