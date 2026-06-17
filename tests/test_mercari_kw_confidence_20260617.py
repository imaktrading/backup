"""Regression: 2026-06-17 — メルカリ keyword検索で変種を確証できない時は画像検索に切替。

keyword検索は番号一致だけだと同名別set(誤variant)/別カードを掴むリスク。set名の語(漢字/カナ/
Latin)が候補名に在る時のみ keyword を信頼し、無ければ自社PSAスラブ画像でメルカリ画像検索に切替
(視覚一致+番号検証で別カード混入を防ぐ)。set-code(OP11等)はカード番号と重複するので確証に使わない。
"""
import importlib.util
from pathlib import Path

_TOOLS = Path(__file__).resolve().parent.parent / "iMakHQ" / "tools"
_spec = importlib.util.spec_from_file_location("mercari_psa_resource_t", _TOOLS / "mercari_psa_resource.py")
import sys
sys.path.insert(0, str(_TOOLS))
mp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mp)

_HINT = ["BOOSTER -A FIST OF DIVINE SPEED- [OP-11]", "神速の拳", "A FIST OF DIVINE SPEED",
         "", "SR", "ゼウス", "OP11-106"]


def test_setname_word_confirms_variant():
    assert mp.kw_variant_confident("PSA10 ゼウス 神速の拳 OP11-106", _HINT) is True


def test_number_only_not_confident_triggers_image():
    # set名の語が無い=番号一致だけ → 確証せず(画像検索へ)。set-code OP11 で誤確証しないこと
    assert mp.kw_variant_confident("PSA10 ゼウス OP11-106", _HINT) is False


def test_no_hint_not_confident():
    assert mp.kw_variant_confident("PSA10 ゼウス OP11-106", None) is False
    assert mp.kw_variant_confident("anything", []) is False


def test_wrong_set_egghead_not_confirmed_by_number():
    # 正=EGGHEAD(EB04)。listingが番号だけ(EGGHEAD無) → 不確証 → 画像検索で視覚確認
    h = ["エクストラブースター EGGHEAD CRISIS【EB-04】", "EGGHEAD CRISIS", "EGGHEAD CRISIS",
         "", "SR", "ゼウス", "OP11-106_EB04"]
    assert mp.kw_variant_confident("PSA10 ゼウス OP11-106", h) is False
    assert mp.kw_variant_confident("PSA10 ゼウス EGGHEAD CRISIS OP11-106", h) is True


def test_fetch_mercari_uses_confidence_for_image_switch():
    src = (_TOOLS / "mercari_psa_resource.py").read_text(encoding="utf-8")
    assert "kw_variant_confident(best[2]" in src       # keyword結果を確証判定
    assert "image_search_fallback" in src              # 不確証 → 画像検索
