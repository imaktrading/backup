"""2026-06-10 回帰: unresolved17 (I)(II) + DB/Gundam set-map.

(I) edition/event matcher 拡張 (B premium + A promo)
(II) resolver brand→category 検出 (番号衝突 ST04-013 OP/Gundam)
②  DB/Gundam brand→set_code (DUAL IMPACT→GD02 等) + colon-split tokenizer (TRUNKS:FUTURE)
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "integrations"))
import psa_to_csv as P  # noqa: E402
import resolver  # noqa: E402


def _promo(num, subj, brand):
    r = P._search_one_piece_promo_by_number(num, subj, brand=brand, verbose=False)
    return r["product_id"] if r else None


# --- (I) edition/event matcher: B premium + A promo ---
def test_op_premium_film_red_uta_opday():
    assert _promo("007", "NAMI", "PREMIUM CARD COLL -FILM RED-") == "ST01-007_p5"
    assert _promo("017", "NICO ROBIN", "PREMIUM CARD COLL -FILM RED-") == "OP01-017_p2"
    assert _promo("120", "UTA", "PREMIUM CARD COLL -UTA-") == "OP02-120_p3"
    assert _promo("109", "MONKEY D LUFFY", "PREMIUM CARD COLL -ONE PIECE DAY24-") == "OP07-109_p2"


def test_op_promo_card_set_and_standard_battle():
    assert _promo("016", "NAMI", "OP PROMOS NAMI PROMOTION CARD SET 1") == "OP01-016_p6"
    assert _promo("044", "KAYA", "OP PROMOS KAYA STANDARD BATTLE WINNER") == "OP03-044_p2"


def test_op_regression_chopper_sabo_unchanged():
    assert _promo("006", "TONY TONY CHOPPER",
                  "ONE PIECE JAPANESE 25TH ANNIVERSARY PREMIUM CARD COLLECTION") == "ST01-006_p1"
    assert _promo("006", "TONY TONY CHOPPER",
                  "ONE PIECE JAPANESE PREMIUM CARD COLLECTION") is None  # generic→fail-closed(promo層None)
    assert _promo("049", "SABO",
                  "ONE PIECE JAPANESE PREMIUM CARD COLLECTION -BEST SELECTION VOL.4-") == "OP10-049_p1"


# --- ② DB/Gundam brand→set_code ---
def test_gundam_dragonball_set_code():
    assert P.extract_set_code_from_brand_gundam("GUNDAM JAPANESE DUAL IMPACT") == "GD02"
    assert P.extract_set_code_from_brand_gundam("GUNDAM JAPANESE NEWTYPE RISING") == "GD01"
    assert P.extract_set_code_from_brand_dragonball(
        "DRAGON BALL SUPER FUSION WORLD MANGA BOOSTER 02") == "SB02"
    assert P.extract_set_code_from_brand_dragonball(
        "DRAGON BALL FUSION WORLD ENERGY MARKER PACK 01") == "E01"


def test_resolve_dbgundam_end_to_end():
    assert resolver.resolve({"category": "gundam_tcg", "signals": {
        "brand": "GUNDAM JAPANESE DUAL IMPACT", "subject": "KIMARIS", "card_no": "070"}}) == "GD02-070"
    assert resolver.resolve({"category": "dragonball_scg", "signals": {
        "brand": "DRAGON BALL SUPER FUSION WORLD MANGA BOOSTER 02",
        "subject": "TRUNKS:FUTURE", "card_no": "001"}}) == "SB02-001"


# --- (II) resolver brand→category (番号衝突分離) ---
def test_resolver_brand_category_collision():
    # bare ST04-013 は OP(X.Drake)/Gundam(Hawk of Endymion) 両方に存在。brand=GUNDAM で gundam に routing
    assert resolver.resolve({"category": "one_piece_tcg", "signals": {
        "brand": "GUNDAM JAPANESE ST04 SEED STRIKE", "subject": "HAWK OF ENDYMION",
        "card_no": "013"}}) == "ST04-013"
    # OP brand は従来どおり OP (回帰: category 誤検出で飛ばさない)
    assert resolver.resolve({"category": "one_piece_tcg", "signals": {
        "brand": "ONE PIECE JAPANESE OP01-ROMANCE DAWN", "subject": "", "card_no": "001"}}) == "OP01-001"


def test_subject_colon_tokenize():
    # 'TRUNKS:FUTURE' が : で分割され name_en 'Trunks : Future' と照合
    assert "TRUNKS" in P._subject_tokens("TRUNKS:FUTURE")
