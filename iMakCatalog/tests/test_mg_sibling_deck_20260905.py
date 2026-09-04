# -*- coding: utf-8 -*-
"""「ミュウツーVSゲノセクト」の2デッキを名前で選び分ける (2026-09-05).

公式は2デッキに **同じ収録商品名・同じ番号 001〜016** を振っている。
PSA のラベルも両方 `MEWTWO VS GENESECT` なので、**ラベルではデッキを決められない**。
catalog は `MG` (ミュウツー) / `MG-G` (ゲノセクト) に分けてあり、
出品くんは **カード名**で正しい方を引けなければならない。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from integrations import psa_to_csv as P  # noqa: E402

BRAND = "POKEMON JAPANESE BW MEWTWO VS GENESECT 30 CARD DECK BATTLE SET"


def test_mewtwo_side():
    r = P.lookup_pokemon(BRAND, "001", "MEWTWO", verbose=False)
    assert r is not None
    assert (r["set_code"], r["card_number"]) == ("MG", "001")
    assert r["name_jp"] == "ミュウツー"


def test_genesect_side_falls_over_to_sibling():
    """同じ 008 でも、名前が ゲノセクト なら MG-G-008 を引く."""
    r = P.lookup_pokemon(BRAND, "008", "GENESECT", verbose=False)
    assert r is not None
    assert (r["set_code"], r["card_number"]) == ("MG-G", "008")
    assert r["name_jp"] == "ゲノセクト"


def test_name_en_is_not_from_the_other_deck():
    """混ざった英語名 (MG-001='Tangela') が戻っていないこと."""
    r = P.lookup_pokemon(BRAND, "001", "MEWTWO", verbose=False)
    assert "Tangela" not in str(r)


def test_unknown_name_is_rejected():
    """どちらのデッキにも無い名前は **引かない** (fail-closed)."""
    assert P.lookup_pokemon(BRAND, "001", "CHARIZARD", verbose=False) is None
