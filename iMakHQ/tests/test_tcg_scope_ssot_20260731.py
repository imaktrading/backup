# -*- coding: utf-8 -*-
"""tcg_scope.is_out_of_scope が build_row と _route_none_to_catalog の両方から呼ばれる SSOT
の回帰テスト (2026-07-31).

Advisor 依頼 `2026-07-29_missing_models_scope_skip_and_resolver.md` §1:
  「片方だけ塞ぐのは不可。**両方から呼んでいることをテストで固定**してください
   (片方の呼び出しが消えても気づけるように)」

さらに §2: DIVERS も本 helper で新規除外 (2026-07-30)。
"""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__),
                                                 "..", "..", "iMakTCG")))


def _read(name):
    """iMakHQ/tools か iMakTCG から file を読み込む (source-level 呼出検査用)。"""
    for base in [os.path.join(os.path.dirname(__file__), "..", "tools"),
                 os.path.normpath(os.path.join(os.path.dirname(__file__),
                                               "..", "..", "iMakTCG"))]:
        p = os.path.join(base, name)
        if os.path.isfile(p):
            with open(p, encoding="utf-8") as f:
                return f.read()
    raise FileNotFoundError(name)


# ------ 1. build_row (psa_to_csv) が is_out_of_scope を呼ぶことを固定 ------

def test_psa_to_csv_calls_is_out_of_scope():
    src = _read("psa_to_csv.py")
    # tcg_scope から import している
    assert re.search(r"from\s+tcg_scope\s+import\s+is_out_of_scope", src), \
        "psa_to_csv.build_row が tcg_scope.is_out_of_scope を import していない"
    # 実際に呼んでいる (import しただけで dead ではないこと)
    assert re.search(r"is_out_of_scope\s*\(", src) or \
           re.search(r"_is_out_of_scope\s*\(", src), \
        "psa_to_csv.build_row が is_out_of_scope を呼んでいない"


# ------ 2. post_psa_review._route_none_to_catalog も同じ helper を呼ぶ ------

def test_route_none_to_catalog_calls_is_out_of_scope():
    src = _read("post_psa_review.py")
    assert re.search(r"from\s+tcg_scope\s+import[^\n]*is_out_of_scope", src), \
        "_route_none_to_catalog が tcg_scope.is_out_of_scope を import していない"
    # _route_none_to_catalog 関数内で is_out_of_scope 呼出があること
    m = re.search(r"def\s+_route_none_to_catalog\b.*?(?=\ndef\s)", src, re.DOTALL)
    assert m, "_route_none_to_catalog 定義が見つからない"
    body = m.group(0)
    assert "is_out_of_scope" in body, \
        "_route_none_to_catalog 本体で is_out_of_scope を呼んでいない (writer 側の skip 抜け=missing_models 汚染再発)"


# ------ 3. is_out_of_scope 真理表: DIVERS 追加、既存挙動維持 ------

def test_scope_helper_returns_true_for_divers():
    """2026-07-29 追加: DIVERS は catalog(SCG) 対象外 (arcade 派生、catalog 実体 0件)。"""
    from tcg_scope import is_out_of_scope
    # detect_franchise_from_brand が Dragon Ball を返しても brand に DIVERS 含めば skip
    oos, reason = is_out_of_scope("Dragon Ball", "DRAGON BALL SUPER DIVERS 4 SON GOKU")
    assert oos, "DIVERS が out-of-scope 判定されない"
    assert "DIVERS" in reason


def test_scope_helper_returns_true_for_all_divers_vol():
    """DIVERS 全 vol (4/7/40th 等) が一括除外される (2026-07-29 Advisor 確定)。"""
    from tcg_scope import is_out_of_scope
    for brand in [
        "DRAGON BALL SUPER DIVERS 4",
        "DRAGON BALL SUPER DIVERS 7",
        "DRAGON BALL SUPER DIVERS ADVANCE PACK DRAGON BALL 40TH ANNIVERSARY",
    ]:
        oos, _ = is_out_of_scope("Dragon Ball", brand)
        assert oos, f"DIVERS variant not skipped: {brand!r}"


def test_scope_helper_returns_true_for_sdbh():
    from tcg_scope import is_out_of_scope
    oos, reason = is_out_of_scope("Dragon Ball Heroes", "SUPER DRAGON BALL HEROES ULTRA GOD MISSION 1")
    assert oos
    assert "SDBH" in reason or "arcade" in reason.lower() or "アーケード" in reason


def test_scope_helper_preserves_existing_out_of_scope():
    from tcg_scope import is_out_of_scope
    assert is_out_of_scope("Yu-Gi-Oh!", "YU-GI-OH! JAPANESE")[0]
    assert is_out_of_scope("Itajaga", "ITAJAGA DRAGON BALL")[0]
    assert is_out_of_scope("Pokemon", "POKEMON JAPANESE SWORD & SHIELD FAMILY POKEMON CARD GAME")[0]


def test_scope_helper_returns_false_for_normal_sets():
    """SCG 本編 / 通常 One Piece / Pokemon 通常は skip しない (recall 損防止)。"""
    from tcg_scope import is_out_of_scope
    assert not is_out_of_scope("Dragon Ball",
        "DRAGON BALL SUPER CARD GAME FUSION WORLD JAPANESE AWAKENED PULSE")[0]
    assert not is_out_of_scope("One Piece", "ONE PIECE JAPANESE OP08-TWO LEGENDS")[0]
    assert not is_out_of_scope("Pokemon", "POKEMON JAPANESE SV4A SHINY TREASURE EX")[0]


def test_detect_franchise_from_brand_handles_divers():
    """DIVERS brand は franchise='Dragon Ball' で返る (SCG 総称)。scope helper 側で除外される。"""
    from tcg_scope import detect_franchise_from_brand
    assert detect_franchise_from_brand("DRAGON BALL SUPER DIVERS 4") == "Dragon Ball"
