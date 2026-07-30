# -*- coding: utf-8 -*-
"""iMakCatalog one_piece resolver: brand modifier-qualified set-name bonus +300 の
回帰テスト (2026-07-31, Advisor 依頼 `2026-07-29_missing_models_scope_skip_and_resolver.md` §3-A).

事象: OP07-051 (500 Years) が OP07-051_p4 (China 2nd ANNIVERSARY) に勝つ (base=10, _p4=0)。
根治: PSA brand の修飾語込み set キーワード (CHINA 2ND ANNIVERSARY 等) が record の
set_name_official に含まれれば +300 を加える。

Advisor 明示ガード:
  - bare 'ANNIVERSARY' 単独では暴発禁止 (2nd/3rd/China/English で別セット)
  - specific → generic の探索順で first-match により誤マッチ回避
"""
import importlib.util
import os
import sys

_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..",
                                      "iMakCatalog"))
_MOD_PATH = os.path.join(_ROOT, "integrations", "psa_to_csv.py")


def _load():
    if _ROOT not in sys.path:
        sys.path.insert(0, _ROOT)
    spec = importlib.util.spec_from_file_location("catalog_psa_int", _MOD_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---- +300 の適用条件 ----

def test_bonus_applied_for_china_2nd_anniversary():
    m = _load()
    brand = "ONE PIECE JAPANESE CHINA 2ND ANNIVERSARY SET"
    sn = "ONE PIECE カードゲーム China 2nd ANNIVERSARY SET"
    assert m._brand_setname_bonus(brand, sn) == 300


def test_bonus_applied_for_english_2nd_anniversary():
    m = _load()
    assert m._brand_setname_bonus(
        "ONE PIECE JAPANESE ENGLISH 2ND ANNIVERSARY SET",
        "ONE PIECE CARD GAME English 2nd ANNIVERSARY SET") == 300


def test_bonus_applied_for_generic_2nd_anniversary_set():
    """brand に region-qualifier が無い場合、generic '2ND ANNIVERSARY SET' で一致。"""
    m = _load()
    assert m._brand_setname_bonus(
        "ONE PIECE JAPANESE 2ND ANNIVERSARY SET",
        "2nd ANNIVERSARY SET") == 300


def test_bonus_applied_for_1st_anniversary_complete_guide():
    m = _load()
    assert m._brand_setname_bonus(
        "ONE PIECE JAPANESE 1ST ANNIVERSARY COMPLETE GUIDE OUBOU TOKUTEN",
        "「ONE PIECE CARD GAME 1st ANNIVERSARY COMPLETE GUIDE」応募特典カード") == 300


# ---- 暴発防止 (Advisor 明示指示) ----

def test_bare_anniversary_alone_never_matches():
    """bare 'ANNIVERSARY' だけで一致してはいけない (2nd/3rd/China/English で別セット)。"""
    m = _load()
    # brand と record に 'ANNIVERSARY' だけあり、修飾語一致なし → 0
    assert m._brand_setname_bonus("ONE PIECE ANNIVERSARY SET", "5th ANNIVERSARY") == 0
    assert m._brand_setname_bonus("SOME OTHER ANNIVERSARY", "GENERIC ANNIVERSARY") == 0


def test_china_specific_wins_over_generic_when_both_match():
    """brand が specific + generic 両方含む場合、specific first-match で採用され、
    specific が set_name_official に無ければ 0 (generic に fallback しない)。

    暴発ケース例: brand='CHINA 2ND ANNIVERSARY SET' + Japanese record の set_name='2nd
    ANNIVERSARY SET' — bare 2nd ANNIVERSARY で match するのでなく、CHINA 2ND ANNIVERSARY
    が優先チェックされ、Japanese record にそれが無いため 0 → China record に +300 が
    集約され、Japanese record は 0 のまま (両方に +300 されない = 正しい区別)。
    """
    m = _load()
    brand = "ONE PIECE JAPANESE CHINA 2ND ANNIVERSARY SET"
    # China record: matches CHINA specific keyword
    sn_china = "ONE PIECE カードゲーム China 2nd ANNIVERSARY SET"
    assert m._brand_setname_bonus(brand, sn_china) == 300
    # Japanese record: CHINA 2ND ANNIVERSARY not in it → 0 (generic fallback しない)
    sn_japanese = "2nd ANNIVERSARY SET"
    assert m._brand_setname_bonus(brand, sn_japanese) == 0


def test_empty_or_none_returns_zero():
    m = _load()
    assert m._brand_setname_bonus("", "2nd ANNIVERSARY SET") == 0
    assert m._brand_setname_bonus("CHINA 2ND ANNIVERSARY", "") == 0
    assert m._brand_setname_bonus(None, None) == 0


def test_no_keyword_in_brand_returns_zero():
    """通常カードは bonus 対象外 (無関係の brand で +300 されないこと)。"""
    m = _load()
    assert m._brand_setname_bonus(
        "ONE PIECE JAPANESE OP08-TWO LEGENDS",
        "ONE PIECE カードゲーム TWO LEGENDS OP-08") == 0
    assert m._brand_setname_bonus(
        "POKEMON JAPANESE SV4A SHINY TREASURE",
        "SV4A SHINY TREASURE") == 0


# ---- _search_one_piece_promo_by_number が brand を受け取り _promo_score に流す ----

def test_search_promo_signature_accepts_brand():
    """関数シグネチャに brand kwarg があること (回帰: 引数を渡し忘れないためのガード)。"""
    m = _load()
    import inspect
    sig = inspect.signature(m._search_one_piece_promo_by_number)
    assert "brand" in sig.parameters, \
        "_search_one_piece_promo_by_number が brand kwarg を受け取らない (+300 bonus 未配線)"


def test_lookup_one_piece_passes_brand_to_promo_helper():
    """lookup_one_piece が _search_one_piece_promo_by_number(brand=...) で brand を渡している
    (source-level 検査。実 DB call は E2E で担保)。
    """
    with open(_MOD_PATH, encoding="utf-8") as f:
        src = f.read()
    import re
    # lookup_one_piece 内で _search_one_piece_promo_by_number(...brand=brand...) 呼出
    m = re.search(r"_search_one_piece_promo_by_number\([^)]*brand\s*=\s*brand", src)
    assert m, "lookup_one_piece が _search_one_piece_promo_by_number へ brand を渡していない"
