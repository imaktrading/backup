"""tcg_parity_check の回帰テスト (2026-06-13 新設・並行ビルド strangler ゲート)。

interpret_diff が「旧→新の差分」を ok/improved/review/regression に正しく分類するか固定。
実データ (tcg_upload_20260613_065522.csv の8 cert) で観測したケースを定着させる:
  - #1 rarity推測除去 = improved / catalog に rarity 有るのに空欄化 = regression
  - #4 汚染除去 (token縮小) = improved / set是正 catalog一致 = improved / set不一致 = regression
  - Irida→Kai 型 (catalog character_name 同期未完) = review (切替前に要解消)
比較は純関数なので DB/網羅に依存せずテストできる。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from tcg_parity_check import interpret_diff, _norm, _tokens


def _sev(col, old, new, rec=None):
    return interpret_diff(col, old, new, rec or {})[0]


# --- 同値は ok (em-dash / 大小 / 空白を吸収) ---
def test_same_value_is_ok():
    assert _sev("C:Set", "Scarlet & Violet—Paradox Rift",
                "Scarlet & Violet—Paradox Rift") == "ok"
    assert _sev("C:Card Name", "Altaria", "altaria  ") == "ok"


# --- #1: catalog に rarity 無 → 推測除去は improved ---
def test_rarity_guess_removed_is_improved():
    assert _sev("C:Rarity", "Common", "", {"rarity_code": ""}) == "improved"


# --- catalog に rarity 有るのに空欄化は regression (情報欠落) ---
def test_rarity_blanked_with_catalog_rarity_is_regression():
    assert _sev("C:Rarity", "Double Rare", "", {"rarity_code": "RR"}) == "regression"


# --- #4: 汚染除去 (token が真部分集合に縮小) は improved ---
def test_pollution_token_shrink_is_improved():
    assert _sev("C:Character", "Zamazenta V Vmax Climax", "Zamazenta V") == "improved"
    assert _sev("C:Card Name", "Zamazenta V Vmax Climax", "Zamazenta V") == "improved"


# --- 旧⊄新 (別token化) や空欄化はそのまま improved にしない ---
def test_character_blanked_is_regression():
    assert _sev("C:Character", "Irida", "") == "regression"


def test_character_changed_unrelated_is_review():
    # Irida→Kai (catalog character_name 同期未完) は token 縮小でないので review
    assert _sev("C:Character", "Irida", "Kai") == "review"


# --- C:Set 是正: catalog set_name_ebay と一致なら improved / 不一致は regression ---
def test_set_correction_matches_catalog_is_improved():
    assert _sev("C:Set", "Sword & Shield—Brilliant Stars", "VMAX Climax",
                {"set_ebay": "VMAX Climax"}) == "improved"


def test_set_new_value_not_matching_catalog_is_regression():
    assert _sev("C:Set", "Brilliant Stars", "Wrong Name",
                {"set_ebay": "VMAX Climax"}) == "regression"


def test_set_change_without_catalog_ref_is_review():
    assert _sev("C:Set", "Old Set", "", {}) == "review"


# --- Features 新規/変更は review (eBay正規値かは目視) ---
def test_features_added_is_review():
    assert _sev("C:Features", "", "Art Card") == "review"


# --- _norm / _tokens の境界 ---
def test_norm_handles_emdash_and_apostrophe():
    assert _norm("Marnie’s—Box") == "marnie's-box"


def test_tokens_strip_possessive():
    assert _tokens("Marnie's Morpeko") == ["marnie", "morpeko"]
