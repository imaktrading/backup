"""2026-06-10 回帰: unresolved17 (I)(II) + DB/Gundam set-map.

⚠️ HQ受入基準: 実 entry (lookup_one_piece(brand,card_no,subject) / resolver.resolve) で検証。
   _search 直叩き(mock)でなく、PSA実signal配置(edition/event語は subject 側のことが多い)で叩く。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "integrations"))
import psa_to_csv as P  # noqa: E402
import resolver  # noqa: E402


def _op(brand, num, subj):
    r = P.lookup_one_piece(brand, num, subj, verbose=False)
    return r.get("card_id") if r else None


# --- (I) A promo (edition/event語が subject 側、brand は generic 'PROMOS') ---
def test_op_promo_subject_side_edition():
    assert _op("ONE PIECE JAPANESE PROMOS", "044", "KAYA STANDARD BATTLE WINNER") == "OP03-044_p2"
    assert _op("ONE PIECE JAPANESE PROMOS", "016", "NAMI PROMOTION CARD SET 1") == "OP01-016_p6"
    assert _op("ONE PIECE JAPANESE PROMOS", "031", "TASHIGI OFFICIAL EVENT PRIZE") == "OP12-031_p2"


# --- (I) B premium (完全形 PREMIUM CARD COLLECTION, edition は brand 側) ---
def test_op_premium_collection_brand_side():
    assert _op("ONE PIECE JAPANESE PREMIUM CARD COLLECTION -FILM RED-", "007", "NAMI") == "ST01-007_p5"
    assert _op("ONE PIECE JAPANESE PREMIUM CARD COLLECTION -FILM RED-", "013", "RORONOA ZORO") == "ST01-013_p3"
    assert _op("ONE PIECE JAPANESE PREMIUM CARD COLLECTION -FILM RED-", "017", "NICO ROBIN") == "OP01-017_p2"
    assert _op("ONE PIECE JAPANESE PREMIUM CARD COLLECTION -UTA-", "120", "UTA") == "OP02-120_p3"
    assert _op("ONE PIECE JAPANESE PREMIUM CARD COLLECTION -ONE PIECE DAY 24-", "109", "MONKEY D LUFFY") == "OP07-109_p2"


def test_op_regression_chopper_sabo():
    assert _op("ONE PIECE JAPANESE 25TH ANNIVERSARY PREMIUM CARD COLLECTION", "006", "TONY TONY CHOPPER") == "ST01-006_p1"
    assert _op("ONE PIECE JAPANESE PREMIUM CARD COLLECTION", "006", "TONY TONY CHOPPER") is None  # generic→fail-closed
    assert _op("ONE PIECE JAPANESE PREMIUM CARD COLLECTION -BEST SELECTION VOL.4-", "049", "SABO") == "OP10-049_p1"


# --- ② DB/Gundam set-map (実 resolve) ---
def test_resolve_dbgundam():
    assert resolver.resolve({"category": "gundam_tcg", "signals": {
        "brand": "GUNDAM JAPANESE DUAL IMPACT", "subject": "KIMARIS", "card_no": "070"}}) == "GD02-070"
    assert resolver.resolve({"category": "dragonball_scg", "signals": {
        "brand": "DRAGON BALL SUPER FUSION WORLD MANGA BOOSTER 02",
        "subject": "TRUNKS:FUTURE", "card_no": "001"}}) == "SB02-001"


# --- (II) brand→category + Gundam starter set-map (252 番号衝突) ---
def test_resolve_gundam_starter_collision():
    # bare ST04-013 は OP(X.Drake)/Gundam(Hawk of Endymion) 衝突。brand 'GUNDAM SEED STRIKE' で gundam ST04 に解決
    assert resolver.resolve({"category": "one_piece_tcg", "signals": {
        "brand": "GUNDAM JAPANESE SEED STRIKE", "subject": "HAWK OF ENDYMION",
        "card_no": "013"}}) == "ST04-013"
    assert P.extract_set_code_from_brand_gundam("GUNDAM JAPANESE SEED STRIKE") == "ST04"


def test_resolve_op_regression_not_misrouted():
    # OP brand は category 誤検出で飛ばさない
    assert resolver.resolve({"category": "one_piece_tcg", "signals": {
        "brand": "ONE PIECE JAPANESE OP01-ROMANCE DAWN", "subject": "", "card_no": "001"}}) == "OP01-001"
