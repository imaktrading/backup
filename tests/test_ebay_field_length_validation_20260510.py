"""Regression: 2026-05-10 eBay Item Specifics フィールド長制限を物理ゲート化.

事故 (ichibankuji_upload_20260510_074232 入稿結果):
  4 件全 Failure - ErrorCode 21919308:
    "Series's value of '...' is too long. Enter a value of no more than 65 characters."
  Claude API が series_name_en に長い文字列 (74 文字) を生成 → C:Series に入った →
  eBay 入稿失敗.

修正方針 (no_modification_chain):
  二段防御:
  1. 上流: ichibankuji_to_csv.py の _truncate_at_word_boundary helper で生成時に短縮
  2. 下流: listing_common.audit_csv_row で EBAY_FIELD_MAX_LEN を読んで物理ゲート

  EBAY_FIELD_MAX_LEN は data dict なので、新フィールドで長さエラーが出たら
  1 行追記するだけ (= データ駆動型バリデータ、修正連鎖を生まない).
"""
from __future__ import annotations
import importlib.util
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_API = _REPO_ROOT / "iMakeBayAPI"
_KUJI = _REPO_ROOT / "iMak_ichibankuji"
if str(_API) not in sys.path:
    sys.path.insert(0, str(_API))


def _load_kuji_module():
    """sys.modules キャッシュ汚染回避用、絶対パスから iMak_ichibankuji/ichibankuji_to_csv.py を load."""
    path = _KUJI / "ichibankuji_to_csv.py"
    spec = importlib.util.spec_from_file_location("_test_kuji_to_csv", str(path))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# ============================================================================
# 下流: listing_common.audit_csv_row + EBAY_FIELD_MAX_LEN
# ============================================================================
def test_ebay_field_max_len_dict_has_series_65():
    """C:Series 65 文字制限が dict に登録済."""
    from listing_common import EBAY_FIELD_MAX_LEN
    assert EBAY_FIELD_MAX_LEN.get("C:Series") == 65


def test_audit_rejects_series_over_65_chars():
    """C:Series 66 文字 → error 化 (= CSV 物理除外)."""
    from listing_common import audit_csv_row
    row_data = {
        "*Title": "Test",
        "*Category": "261055",
        "*StartPrice": "50.00",
        "ConditionID": "1000",
        "C:Series": "A" * 66,  # 66 chars
    }
    violations = audit_csv_row(row_data, category="ichibankuji")
    series_errors = [v for v in violations if v[0] == "C:Series" and v[2] == "error"]
    assert len(series_errors) == 1, f"Expected 1 C:Series error, got: {series_errors}"


def test_audit_accepts_series_at_65_chars():
    """C:Series 65 文字ぴったり → error なし."""
    from listing_common import audit_csv_row
    row_data = {
        "*Title": "Test",
        "*Category": "261055",
        "*StartPrice": "50.00",
        "ConditionID": "1000",
        "C:Series": "A" * 65,  # 65 chars
    }
    violations = audit_csv_row(row_data, category="ichibankuji")
    series_errors = [v for v in violations if v[0] == "C:Series" and v[2] == "error"]
    assert series_errors == [], f"Expected no C:Series error at 65 chars, got: {series_errors}"


def test_audit_5_9_actual_failed_string_rejected():
    """5/9 実事故文字列 (74 文字) は error."""
    from listing_common import audit_csv_row
    row_data = {
        "*Title": "Test",
        "*Category": "261055",
        "*StartPrice": "91.98",
        "ConditionID": "1000",
        "C:Series": "Ichiban Kuji One Piece Monkey D Luffy Adventure Memories and Future Course",
    }
    assert len(row_data["C:Series"]) == 74
    violations = audit_csv_row(row_data, category="ichibankuji")
    series_errors = [v for v in violations if v[0] == "C:Series" and v[2] == "error"]
    assert len(series_errors) == 1


# ============================================================================
# 上流: _truncate_at_word_boundary
# ============================================================================
def test_truncate_short_string_unchanged():
    """max_len 以内の text は無変化."""
    m = _load_kuji_module()
    assert m._truncate_at_word_boundary("short", 65) == "short"
    assert m._truncate_at_word_boundary("A" * 65, 65) == "A" * 65


def test_truncate_long_string_at_word_boundary():
    """5/9 事故ケース: 74 文字 → 65 以内で word 境界切り."""
    m = _load_kuji_module()
    text = "Ichiban Kuji One Piece Monkey D Luffy Adventure Memories and Future Course"
    out = m._truncate_at_word_boundary(text, 65)
    assert len(out) <= 65
    assert " " not in out[-1]  # 末尾に空白なし
    # word 境界切りされているので部分単語 "Futu" や "Cours" は出ない
    last_word = out.rsplit(" ", 1)[-1]
    assert last_word in text.split(), f"Last word {last_word!r} should be a complete word"


def test_truncate_no_space_falls_back_to_hard_cut():
    """空白なしの長文字列は hard cut (rfind(' ') < 7割位置 → max_len で切る)."""
    m = _load_kuji_module()
    text = "A" * 100
    out = m._truncate_at_word_boundary(text, 65)
    assert len(out) == 65


def test_truncate_empty_string():
    """空文字列はそのまま."""
    m = _load_kuji_module()
    assert m._truncate_at_word_boundary("", 65) == ""
    assert m._truncate_at_word_boundary(None, 65) is None


def test_truncate_5_9_specific_result_passes_validator():
    """上流 truncate 後の文字列が下流 validator を通る (二段防御の整合確認)."""
    from listing_common import audit_csv_row
    m = _load_kuji_module()
    raw = "Ichiban Kuji One Piece Monkey D Luffy Adventure Memories and Future Course"
    truncated = m._truncate_at_word_boundary(raw, 65)
    row_data = {
        "*Title": "Test",
        "*Category": "261055",
        "*StartPrice": "91.98",
        "ConditionID": "1000",
        "C:Series": truncated,
    }
    violations = audit_csv_row(row_data, category="ichibankuji")
    series_errors = [v for v in violations if v[0] == "C:Series" and v[2] == "error"]
    assert series_errors == [], f"Truncated string should pass validator, got: {series_errors}"
