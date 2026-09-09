# -*- coding: utf-8 -*-
"""仕入値の下落アラートに、出品でない行を混ぜない (2026-09-10 実害).

商品管理シートには itemID `9999` (見送りの目印) の行が **37行** ある。
台帳は itemID をキーにしているので 37行が1つの枠を取り合い、書いた順で
「前回 84,999円」になる。別の行が今日 4,000円だと「95%下がった」と誤報した。
実際: その朝の14件のうち **4件がこれ** で、出品ですらないので確認しようがない。
"""
import os
import sys

TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
sys.path.insert(0, TOOLS)

import supply_card_mismatch as M          # noqa: E402


def test_placeholder_is_not_a_listing():
    assert M.is_real_listing_id("9999") is False
    assert M.is_real_listing_id("") is False
    assert M.is_real_listing_id(None) is False
    assert M.is_real_listing_id("abc") is False


def test_real_ebay_ids_pass():
    assert M.is_real_listing_id("358806710830") is True
    assert M.is_real_listing_id("820070750789") is True


def test_drop_watcher_skips_placeholder_rows():
    """37行が1枠を取り合う形にならないこと (誤報の再発防止)。"""
    src = open(os.path.join(TOOLS, "supply_card_mismatch.py"), encoding="utf-8").read()
    i = src.index("def find_cost_drops(")
    body = src[i:src.index(chr(10) + "def ", i + 10)]
    assert "is_real_listing_id(iid)" in body, "出品でない行を先に外すこと"
