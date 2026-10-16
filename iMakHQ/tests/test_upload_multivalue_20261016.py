# -*- coding: utf-8 -*-
"""2026-10-16 API の入稿 (AddFixedPriceItem) が CSV の「A|B」を1つの値で送っていた (FileExchange では縦棒=複数の値)。
実例 820244750527 Features ['Promo|Starter Deck'] → eBay の絞り込み (Features=Promo) に当たらない。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))


def test_pipe_becomes_separate_values():
    import ebay_upload_csv as U
    xml = U.build_item_xml({"*Title": "t", "C:Features": "Promo|Starter Deck", "C:Game": "Pokémon TCG"})
    assert "<Name>Features</Name><Value>Promo</Value><Value>Starter Deck</Value>" in xml
    assert "<Name>Game</Name><Value>Pokémon TCG</Value>" in xml
    assert "Promo|Starter Deck" not in xml
