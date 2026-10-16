"""目視で同じカードの別個体は1回答えれば済む (2026-10-16 ユーザー「同じカードが出てる。おかしいやん」)。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import post_psa_review as P  # noqa: E402


def _t(cert, subj, brand="POKEMON JAPANESE XY BLUE SHOCK", no="", cat="pokemon_tcg"):
    return {"cert": cert, "subject": subj, "brand": brand, "card_number": no, "category": cat}


def test_same_label_follows_first():
    ts = [_t("1", "ZOROARK BREAK BLUE SHOCK-1ST EDITION"), _t("2", "OTHER"),
          _t("3", "zoroark break blue shock-1st edition ")]
    assert P.same_card_leads(ts) == {"3": "1"}


def test_different_brand_or_number_is_not_same():
    ts = [_t("1", "ZOROARK BREAK"), _t("2", "ZOROARK BREAK", brand="POKEMON JAPANESE THE BEST OF XY"),
          _t("3", "ZOROARK BREAK", no="12"), _t("4", "ZOROARK BREAK", cat="one_piece_tcg")]
    assert P.same_card_leads(ts) == {}


def test_empty_subject_never_grouped():
    assert P.same_card_leads([_t("1", ""), _t("2", "")]) == {}
