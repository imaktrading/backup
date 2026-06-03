"""Regression: 2026-06-03 Item Specifics 日本語混入 fail-closed ガード.

【背景】
Gundam RP-009 の catalog name_en が空 → pipeline が C:Card Name / C:Character を
日本語 name_jp 'リソース' でフォールバック埋め → eBay US 出品の Item Specifics に
日本語が漏れた (タイトルは別経路で英語 'Resource' になっていたため不整合)。

【対策 = 再発防止】
apply_ebay_filter_to_row に fail-closed ガード追加: C:* 値に日本語 codepoint が
混入したら空欄化 (= 出品の正確性原則 / 空欄 > 誤り)。英単語 'Japanese' や em-dash は
日本語 codepoint を含まないので無影響。ef (ebay_filter_masters) 有無に関わらず実行。
"""
from __future__ import annotations
import importlib.util
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TCG = _REPO_ROOT / "iMakTCG"
if str(_TCG) not in sys.path:
    sys.path.insert(0, str(_TCG))

# 同名 module 'psa_to_csv' が iMakCatalog/integrations 側にも存在し sys.modules を汚染するため、
# iMakTCG のファイルを一意名で明示ロードして分離 (= テスト間衝突回避)。
_spec = importlib.util.spec_from_file_location(
    "psa_to_csv_tcg_jpguard", str(_TCG / "psa_to_csv.py")
)
psa_to_csv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(psa_to_csv)


def test_contains_japanese_detects_kana_kanji():
    f = psa_to_csv._contains_japanese
    assert f("リソース") is True          # カタカナ
    assert f("ばくれつ") is True          # ひらがな
    assert f("超新星") is True            # 漢字
    assert f("Resource リソース") is True  # 英日混在
    assert f("ｶﾀｶﾅ") is True             # 半角カナ


def test_contains_japanese_passes_english_and_symbols():
    f = psa_to_csv._contains_japanese
    assert f("Resource") is False
    assert f("Japanese") is False                          # 英単語 (codepoint は ASCII)
    assert f("Scarlet & Violet—Surging Sparks") is False   # em-dash は対象外
    assert f("051/172") is False
    assert f("") is False
    assert f(None) is False


def _reset_report():
    for k in psa_to_csv._EBAY_FILTER_REPORT:
        psa_to_csv._EBAY_FILTER_REPORT[k] = 0 if not k.endswith("samples") else []


def test_apply_filter_blanks_japanese_item_specific():
    """C:* 列に日本語が入っていたら空欄化され、jp_blanked がカウントされる."""
    _reset_report()
    spec_map = psa_to_csv.EBAY_SPEC_TO_CSV
    # 'Character' aspect → csv_col を取得 (無ければ任意の 1 つ)
    csv_col = spec_map.get("Character") or next(iter(spec_map.values()))
    headers = [csv_col]
    row = ["リソース"]
    out = psa_to_csv.apply_ebay_filter_to_row(row, headers, category="gundam")
    assert out[0] == "", f"日本語が空欄化されていない: {out[0]!r}"
    assert psa_to_csv._EBAY_FILTER_REPORT["jp_blanked"] >= 1


def test_apply_filter_keeps_english_item_specific():
    """英語値 (日本語 codepoint なし) は jp_blanked ガードで消されない."""
    _reset_report()
    spec_map = psa_to_csv.EBAY_SPEC_TO_CSV
    csv_col = spec_map.get("Character") or next(iter(spec_map.values()))
    headers = [csv_col]
    row = ["Resource"]
    psa_to_csv.apply_ebay_filter_to_row(row, headers, category="gundam")
    # jp ガードは英語をカウントしない (ef 側で blank される可能性は別軸なのでここでは見ない)
    assert psa_to_csv._EBAY_FILTER_REPORT["jp_blanked"] == 0
