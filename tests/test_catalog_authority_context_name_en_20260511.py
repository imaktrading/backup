"""Regression: 2026-05-11 catalog_authority_context は Pokemon name_en を 3AI に提示する.

【背景】
5/11 8:51 PSA TCG 走行で 3AI selfcheck が SV3-119 ピジョン (Pidgeotto) と
SV-P-232 ナンジャモのカイデン (Iono's Wattrel) を BLOCK。Catalog Claude が
公式 pokemon-card.com で fact-check したところ catalog の name_en は正解で、
3AI prompt が name_jp のみ提示 → 直訳で誤訳 BLOCK が原因と判明。
"""
from __future__ import annotations
import importlib.util
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TCG = _REPO_ROOT / "iMakTCG"


def _load_module():
    """psa_to_csv の名前衝突を避けるため path 指定で直接 load."""
    path = _TCG / "catalog_authority_context.py"
    if str(_TCG) not in sys.path:
        sys.path.insert(0, str(_TCG))
    spec = importlib.util.spec_from_file_location("_test_cat_auth_ctx", str(path))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_pokemon_context_includes_both_name_jp_and_en():
    """source 内に name_jp / name_en 両方の参照と prompt 行が存在."""
    src = (_TCG / "catalog_authority_context.py").read_text(encoding='utf-8')
    assert 'catalog_name_jp = (record.get("name_jp") or "").strip()' in src
    assert 'catalog_name_en = (record.get("name_en") or "").strip()' in src
    assert "card_name(JP):" in src
    assert "card_name(EN):" in src


def test_prompt_warns_against_direct_translation():
    """3AI 向け prompt に「直訳禁止、name_en を正規」ルールが含まれる."""
    src = (_TCG / "catalog_authority_context.py").read_text(encoding='utf-8')
    # 例示で典型誤訳 (Pidgeot/Pidgeotto, Kaiden/Wattrel) に言及
    assert "Pidgeotto" in src
    assert "Wattrel" in src
    # 直訳禁止のルール文
    assert "直訳" in src and "正規" in src


def test_pokemon_context_runtime_with_mock_record():
    """mock catalog で _pokemon_context が name_jp + name_en 両方を context に含める."""
    mod = _load_module()

    class _MockCatalog:
        @staticmethod
        def lookup_pokemon(brand, card_number, subject, verbose=False):
            return {
                "card_id": "SV3-119",
                "name_jp": "ピジョン",
                "name_en": "Pidgeotto",
                "set_name_ebay": "Ruler of the Black Flame",
                "type_en": "Colorless",
                "rarity": "AR",
            }

    ctx = mod._pokemon_context(
        _MockCatalog(),
        brand="POKEMON JAPANESE RULER OF THE BLACK FLAME",
        card_number="119",
        subject="PIDGEOTTO ART",
    )
    assert ctx is not None
    assert "ピジョン" in ctx
    assert "Pidgeotto" in ctx
    # JP / EN 両ラベル併記
    assert "card_name(JP):" in ctx
    assert "card_name(EN):" in ctx


def test_pokemon_context_returns_none_on_miss():
    """catalog miss 時は None 返却 (フォールバック維持)."""
    mod = _load_module()

    class _MissCatalog:
        @staticmethod
        def lookup_pokemon(brand, card_number, subject, verbose=False):
            return None

    ctx = mod._pokemon_context(_MissCatalog(), "BRAND", "999", "X")
    assert ctx is None
