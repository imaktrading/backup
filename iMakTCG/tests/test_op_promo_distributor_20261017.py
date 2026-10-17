# -*- coding: utf-8 -*-
"""B-20261017-004: 日本語プロモの拾い直しで英語版の行 (_EN) は当てない。配布元の名前では寄せない (目視で _P が選ばれている)。"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "iMakCatalog"))
from integrations import psa_to_csv as P


def _rec(pid, sn, name="Monkey.D.Luffy"):
    return {"product_id": pid, "set_name_official": sn, "name": name}


def _pick(brand, subject, recs):
    return max(recs, key=lambda r: P._promo_rank(brand, subject, r))["product_id"]


RECS = [_rec("OP07-073", "BOOSTER PACK -500 YEARS IN THE FUTURE- [OP07]"),
        _rec("OP07-073_P_EN", "Promotion Card"),
        _rec("OP07-073_P", "プロモーションカード", "モンキー・D・ルフィ"),
        _rec("OP07-073_p1", "BANDAI CARD GAMES Fest 25-26 in Tokyo 来場記念品", "モンキー・D・ルフィ")]


def test_fest_subject_picks_ja_promo_not_en():
    assert _pick("ONE PIECE JAPANESE PROMOS", "MONKEY D. LUFFY BANDAI CARD GAMES FEST", RECS) == "OP07-073_P"


def test_japanese_never_picks_en_row():
    assert _pick("ONE PIECE JAPANESE PROMOS", "MONKEY D. LUFFY", RECS) == "OP07-073_P"


def test_english_brand_still_can_pick_en_row():
    assert _pick("ONE PIECE PROMOS", "MONKEY D. LUFFY", RECS) in ("OP07-073_P_EN", "OP07-073_P")
