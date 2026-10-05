"""オファーが来ている PSA の出品も、売れた PSA と同じ探し方で安い仕入元を探す (2026-10-05 ユーザー要望)。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import psa_sold_cheapest as P  # noqa: E402


def test_offer_targets_psa_only_and_once():
    offers = [
        {"itemId": "1", "title": "PSA 10 Pokemon Japanese Pikachu", "cat": "TCG(PSA10)", "price": 80.0,
         "list": 100.0, "sym": "$", "expire": "2026-10-06 10:00", "buyer": "b1"},
        {"itemId": "1", "title": "PSA 10 Pokemon Japanese Pikachu", "cat": "TCG(PSA10)", "price": 85.0,
         "list": 100.0, "sym": "$", "expire": "2026-10-06 11:00", "buyer": "b2"},
        {"itemId": "2", "title": "G-SHOCK GA-2100", "cat": "G-SHOCK", "price": 90.0, "list": 120.0},
    ]
    got = P.offer_targets(offers)
    assert [g["item_id"] for g in got] == ["1"]
    assert got[0]["order"] == "" and "オファー $80.0" in got[0]["note"]


def test_offer_page_title_differs():
    h = P.build_html([], offers=True)
    assert "オファーが来ている PSA の仕入れ先" in h
    assert "PSA10 売れた分の仕入れ先" in P.build_html([])
