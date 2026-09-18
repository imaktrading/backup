"""知らないゲームは通さない (2026-09-19・提案4 fail-closed)。

実害: TOPPS / UPPER DECK / PARKHURST / INDIAN GUM 等のスポーツカードが
「対象外」と判定されず、TCG の候補として13日連続で再評価されていた
(2026-09-17 実測: live の該当9件とも is_out_of_scope が False)。
"""
import sys

sys.path.insert(0, r"C:/dev/iMak/iMakTCG")
from tcg_scope import is_out_of_scope, detect_franchise_from_brand


def _oos(brand):
    return is_out_of_scope(detect_franchise_from_brand(brand), brand)


def test_スポーツカードは対象外():
    for b in ("TOPPS A.L. BOMBERS", "UPPER DECK FRANK WHITE", "PARKHURST LARRY ZEIDEL",
              "INDIAN GUM", "PANINI PRIZM", "LEAF METAL"):
        assert _oos(b)[0] is True, b


def test_扱っているゲームは通る():
    for b in ("POKEMON JAPANESE SV11W-WHITE FLARE", "ONE PIECE JAPANESE OP08-001",
              "DRAGON BALL SUPER CARD GAME FB01", "GUNDAM DUAL IMPACT"):
        assert _oos(b) == (False, ""), b


def test_brandが空なら落とさない():
    """PSA をまだ引けていない = 分からないだけ。目視に回す (従来どおり)。"""
    assert is_out_of_scope("", "") == (False, "")
