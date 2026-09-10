# -*- coding: utf-8 -*-
"""スタートデッキ100 (SI) とコロコロコミックver. (SN) の番号衝突 (2026-09-10).

cert 146711355: Brand に COROCORO COMIC VERSION が入っているのに、番号だけでは
SI-008 (キノココ) が先にヒットしてしまい、PSA Subject 'SNORLAX' と名前不一致で reject
されていた。正しくは SN-008 (カビゴン)。兄弟デッキ機構で名前一致側 (SN) に倒す。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from integrations import psa_to_csv as P  # noqa: E402

BRAND_COROCORO = "POKEMON JAPANESE SWORD & SHIELD START DECK 100 COROCORO COMIC VERSION"
BRAND_PLAIN = "POKEMON JAPANESE SWORD & SHIELD START DECK 100"


def test_corocoro_snorlax_falls_over_to_sn():
    """cert146711355: SNORLAX という名前で SN-008 (カビゴン) を引く."""
    r = P.lookup_pokemon(BRAND_COROCORO, "008", "SNORLAX SD.100 COROCORO COMIC VER.", verbose=False)
    assert r is not None
    assert (r["set_code"], r["card_number"]) == ("SN", "008")
    assert r["name_jp"] == "カビゴン"


def test_plain_start_deck_100_unchanged():
    """コロコロ表記が無い正常ケース (cert135877476) は SI を直接 hit (回帰なし)."""
    r = P.lookup_pokemon(BRAND_PLAIN, "128", "RAICHU", verbose=False)
    assert r is not None
    assert (r["set_code"], r["card_number"]) == ("SI", "128")
    assert r["name_jp"] == "ライチュウ"


def test_unknown_name_is_rejected():
    """SI にも SN にも合わない名前は引かない (fail-closed)."""
    assert P.lookup_pokemon(BRAND_COROCORO, "008", "CHARIZARD", verbose=False) is None
