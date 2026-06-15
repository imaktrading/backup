"""Regression: 2026-06-15 — TCG から 3AI 合議を完全削除した状態を固定する.

経緯: 「3AI 撤去 (1f4d9c9)」は実体としては validate_and_report を catalog_confirmed=True
で force-skip しているだけで、3AI 配線(validate_and_report 呼出 / catalog_authority_context /
"(3AI skip)" ログ)は丸ごと残っていた。本コミットで TCG を決定論検証(validate_row)直呼びに
置換し、TCG 専用の 3AI モジュールを物理削除した。

この test は「TCG の生成経路に 3AI が二度と戻らない」ことを source レベルで固定する。
共有 listing_validator.validate_and_report は Mercari (montbell/tshirt) が継続使用するため
削除対象外 = ここでは検査しない。
"""
from pathlib import Path

_TCG = Path(__file__).resolve().parent.parent / "iMakTCG"
_SRC = (_TCG / "psa_to_csv.py").read_text(encoding="utf-8")


def test_psa_to_csv_does_not_wire_3ai():
    # 3AI 合議の入口(validate_and_report)を TCG が呼ばない
    assert "validate_and_report" not in _SRC, "psa_to_csv が 3AI validate_and_report を呼んでいる"
    # 3AI context 注入モジュールを参照しない
    assert "catalog_authority_context" not in _SRC, "psa_to_csv が削除済 catalog_authority_context を参照"
    # 3AI 議論の関数を呼ばない
    assert "deliberate_3ai" not in _SRC
    assert "_override_context" not in _SRC


def test_psa_to_csv_uses_deterministic_validate_row():
    # 決定論検証(誤出品防止)は validate_row 直呼びで維持されている
    assert "from listing_validator import validate_row" in _SRC
    assert "validate_row(" in _SRC


def test_tcg_3ai_module_deleted():
    assert not (_TCG / "catalog_authority_context.py").exists(), "TCG 専用 3AI モジュールが残っている"
