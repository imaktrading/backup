"""KEY再設計 Step3: catalog resolver facade 回帰テスト.

resolve(context) → canonical product_id | url-key | "" (fail-closed).
既存 lookup_*/promo-scoring を dispatch集約。判別不能/未対応は ""。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import resolver  # noqa: E402


def _r(category=None, **signals):
    return resolver.resolve({"category": category, "signals": signals})


def test_op_sabo_best_selection():
    assert _r("one_piece_tcg",
              brand="ONE PIECE JAPANESE PREMIUM CARD COLLECTION -BEST SELECTION VOL.4-",
              subject="SABO", card_no="049") == "OP10-049_p1"


def test_op_chopper_25th_resolves_p1():
    assert _r("one_piece_tcg",
              brand="ONE PIECE JAPANESE 25TH ANNIVERSARY PREMIUM CARD COLLECTION",
              subject="TONY TONY CHOPPER", card_no="006") == "ST01-006_p1"


def test_op_chopper_generic_failclosed():
    # edition句無し → 判別不能 → "" (誤出品せず、EB01も選ばない)
    assert _r("one_piece_tcg",
              brand="ONE PIECE JAPANESE PREMIUM CARD COLLECTION",
              subject="TONY TONY CHOPPER", card_no="006") == ""


def test_pokemon_fusion_arts_setcode():
    assert _r("pokemon_tcg",
              brand="POKEMON JAPANESE SWORD & SHIELD FUSION ARTS",
              subject="BOLTUND VMAX", card_no="035") == "S8-035"


def test_category_alias():
    assert _r("op", brand="ONE PIECE JAPANESE OP01-ROMANCE DAWN",
              subject="", card_no="001") == "OP01-001"


def test_gshock_no_model_failclosed():
    # gshock は対応済だが model signal 無 → "" (brand だけでは解決しない)
    assert _r("gshock", brand="x") == ""
    assert _r("gshock") == ""


# === G-shock dispatch (2026-06-12 BUILD greenlight: dedupe 全除外の真因配線) ===
def test_gshock_canonical_self():
    # canonical suffix形 → 自身
    assert _r("gshock", model="DW-5600RL-1JF") == "DW-5600RL-1JF"
    assert _r("gshock", model="GA-V01SKE-6A") == "GA-V01SKE-6A"


def test_gshock_bare_alias_to_canonical():
    # 短縮形 bare (1:1 alias) → canonical suffix形に解決
    assert _r("gshock", model="GM-700G-9A") == "GM-700G-9AJF"


def test_gshock_true_1n_failclosed():
    # 真の 1:N 曖昧 bare → "" (推測しない)
    assert _r("gshock", model="GW-9400J-1B") == ""


def test_gshock_unregistered_failclosed():
    # catalog 未収録 → "" (誤出品せず skip)
    assert _r("gshock", model="NONEXIST-9999-9Z") == ""


def test_gshock_empty_model_failclosed():
    assert _r("gshock", model="") == ""


def test_missing_signals_failclosed():
    assert _r("one_piece_tcg") == ""
    assert resolver.resolve({}) == ""
    assert resolver.resolve(None) == ""


def test_marketplace_url_key():
    assert _r(None, url="https://jp.mercari.com/item/m12345678?ref=x") == "item:m12345678"
    assert _r(None, url="https://mercari-shops.com/shops/products/abc123") == "shops:abc123"


# ============================================================================
# Phase2a: resolve_with_category (2026-07-27 HQ依頼) — KEY category prefix の起点
# ============================================================================
def _rc(category=None, **signals):
    return resolver.resolve_with_category({"category": category, "signals": signals})


def test_with_category_backward_compat_equals_resolve():
    """resolve_with_category.product_id は既存 resolve() と常に一致 (非破壊)."""
    ctxs = [
        {"category": "one_piece_tcg", "signals": {
            "brand": "ONE PIECE JAPANESE 25TH ANNIVERSARY PREMIUM CARD COLLECTION",
            "subject": "TONY TONY CHOPPER", "card_no": "006"}},
        {"category": "pokemon_tcg", "signals": {
            "brand": "POKEMON JAPANESE ABYSS EYE", "card_no": "001", "subject": "TROPIUS"}},
        {"category": "gundam_tcg", "signals": {
            "brand": "GUNDAM JAPANESE ST02-WINGS", "card_no": "010", "subject": "HEERO YUY"}},
    ]
    for c in ctxs:
        assert resolver.resolve(c) == resolver.resolve_with_category(c)["product_id"]


def test_with_category_disambiguates_st02_010_collision():
    """同一 product_id 'ST02-010' が category で分離される (案B の核心)."""
    g = _rc("gundam_tcg", brand="GUNDAM JAPANESE ST02-WINGS", card_no="010", subject="HEERO YUY")
    o = _rc("one_piece_tcg", brand="ONE PIECE JAPANESE ST02", card_no="010", subject="BASIL HAWKINS")
    assert g == {"product_id": "ST02-010", "category": "gundam_tcg"}
    assert o == {"product_id": "ST02-010", "category": "one_piece_tcg"}


def test_with_category_pokemon():
    d = _rc("pokemon_tcg", brand="POKEMON JAPANESE ABYSS EYE", card_no="001", subject="TROPIUS")
    assert d == {"product_id": "M5-001", "category": "pokemon_tcg"}


def test_with_category_url_key_has_empty_category():
    """url-key は catalog-backed でない → category="" (KEY prefix 対象外)."""
    d = _rc(None, url="https://mercari.com/item/m123456")
    assert d["category"] == ""
    assert d["product_id"].startswith("item:")


def test_with_category_failclosed_empty_both():
    d = _rc("gundam_tcg", brand="GUNDAM JAPANESE ST02", card_no="999", subject="NOBODY")
    assert d == {"product_id": "", "category": ""}
