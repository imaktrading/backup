"""Regression: 2026-06-16 — TCG の Claude モデル名を1箇所集約 (SSOT)。

経緯: `claude-sonnet-4-20250514` が 2026-06-15 に retire → 全 TCG スクリプトで 404。
原因はモデル名が card_identifier / psa_to_csv (×2) / check_csv の4箇所にベタ書きされ、
廃止時に4箇所同時に死んだこと。card_identifier.CLAUDE_MODEL を唯一の真実とし、他は参照する。

この test は (1) retire 済モデルがコードに残っていない (2) モデル名リテラルが card_identifier
1箇所のみ (3) psa_to_csv / check_csv は CLAUDE_MODEL を参照、を source レベルで固定する。
"""
from pathlib import Path

_TCG = Path(__file__).resolve().parent.parent / "iMakTCG"
_RETIRED = "claude-sonnet-4-20250514"


def test_retired_model_not_referenced():
    for name in ("card_identifier.py", "psa_to_csv.py", "check_csv.py"):
        src = (_TCG / name).read_text(encoding="utf-8")
        assert _RETIRED not in src, f"{name} に retire 済モデル {_RETIRED} が残存"


def test_card_identifier_is_the_single_source():
    src = (_TCG / "card_identifier.py").read_text(encoding="utf-8")
    assert 'CLAUDE_MODEL = "claude-sonnet-4-6"' in src, "SSOT 定数が現行モデルでない"


def test_callers_reference_the_constant_not_a_literal():
    # psa_to_csv / check_csv はモデル名リテラルを持たず CLAUDE_MODEL を参照する
    for name in ("psa_to_csv.py", "check_csv.py"):
        src = (_TCG / name).read_text(encoding="utf-8")
        assert "from card_identifier import CLAUDE_MODEL" in src, f"{name} が SSOT を import していない"
        assert "model=CLAUDE_MODEL" in src, f"{name} が CLAUDE_MODEL を使っていない"
        assert '"claude-sonnet' not in src, f"{name} にモデル名リテラルが残存"
