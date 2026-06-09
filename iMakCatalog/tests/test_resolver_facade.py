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


def test_unsupported_category_failclosed():
    assert _r("gshock", brand="x") == ""


def test_missing_signals_failclosed():
    assert _r("one_piece_tcg") == ""
    assert resolver.resolve({}) == ""
    assert resolver.resolve(None) == ""


def test_marketplace_url_key():
    assert _r(None, url="https://jp.mercari.com/item/m12345678?ref=x") == "item:m12345678"
    assert _r(None, url="https://mercari-shops.com/shops/products/abc123") == "shops:abc123"
