"""Regression: Title SEO 拡張 (2026-05-01) — 短タイトル問題の構造解消.

事故 (毎 run 観測): check_csv が 7-11 件中 6-9 件で「タイトル <70 字」WARN.
  TOP セラーが頻用する SEO 単語 (年, japanese, sword/shield 等) が
  - BANNED_TITLE_WORDS で削除される (japanese/japan)
  - _UNIVERSAL_SEO_PERMITTED_TOKENS が厳しすぎて refine_title で追加されない
ため、build_title 出力 (50-65 字) のままタイトル長が伸びない構造的問題.

修正方針 (本体 logic 不変、list 拡張のみ):
  Fix 1: psa_to_csv.BANNED_TITLE_WORDS から "japanese", "japan" 削除
         (事実情報、TOP 競合 11/15 件で使用、SEO 価値高).
  Fix 2: title_generation_agent._UNIVERSAL_SEO_PERMITTED_TOKENS に追加:
         - 地域: japanese / jp / jpn
         - 年: 2019-2026
         - Pokemon era: sword / shield / sun / moon / scarlet / violet / xy
         - 一般 set descriptor: promo / promos / collection / anniversary / starter / set

期待効果: 平均タイトル 50-65 字 → 70-80 字、検索ヒット率向上.
"""
from __future__ import annotations
import importlib.util
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TCG = _REPO_ROOT / "iMakTCG"
if str(_TCG) not in sys.path:
    sys.path.insert(0, str(_TCG))


def _load_module_by_path(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, str(path))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


_psa_tcg = _load_module_by_path(_TCG / "psa_to_csv.py", "_test_psa_to_csv_seo")
_title_agent = _load_module_by_path(
    _TCG / "title_generation_agent.py", "_test_title_agent_seo"
)


# ============================================================================
# Fix 1: BANNED_TITLE_WORDS から japanese/japan 削除
# ============================================================================
def test_japanese_no_longer_banned():
    """'japanese' が BANNED から外れた (TOP 競合多数使用、SEO 価値高)."""
    banned = _psa_tcg.BANNED_TITLE_WORDS
    assert "japanese" not in banned
    assert "japan" not in banned


def test_strip_banned_words_keeps_japanese():
    """strip_banned_words が 'japanese' を残すこと (Title に明示的に書ける)."""
    fn = _psa_tcg.strip_banned_words
    title = "PSA 10 Pokemon 2024 Japanese Sword Shield Charizard ex"
    result = fn(title)
    assert "Japanese" in result or "japanese" in result.lower()


def test_strip_banned_words_still_removes_spam():
    """SEO スパム ('look', 'wow', 'gem mt' 等) は引き続き削除される (副作用ゼロ)."""
    fn = _psa_tcg.strip_banned_words
    assert "look" not in fn("Pokemon LOOK Charizard").lower()
    assert "wow" not in fn("Pokemon WOW Charizard").lower()
    assert "gem mt" not in fn("Pokemon GEM MT Charizard").lower()


# ============================================================================
# Fix 2: _UNIVERSAL_SEO_PERMITTED_TOKENS 拡張
# ============================================================================
def test_seo_whitelist_includes_year_tokens():
    """年 (2019-2026) が SEO 安全リストに含まれる."""
    pool = _title_agent._UNIVERSAL_SEO_PERMITTED_TOKENS
    for year in ["2019", "2020", "2021", "2022", "2023", "2024", "2025", "2026"]:
        assert year in pool, f"{year} 不在"


def test_seo_whitelist_includes_japanese_terms():
    """japanese / jp / jpn が SEO 安全リスト."""
    pool = _title_agent._UNIVERSAL_SEO_PERMITTED_TOKENS
    assert "japanese" in pool
    assert "jp" in pool
    assert "jpn" in pool


def test_seo_whitelist_includes_pokemon_era_tokens():
    """Pokemon シリーズ era 名 (Sword/Shield/Sun/Moon/Scarlet/Violet/XY)."""
    pool = _title_agent._UNIVERSAL_SEO_PERMITTED_TOKENS
    for era in ["sword", "shield", "sun", "moon", "scarlet", "violet", "xy"]:
        assert era in pool, f"{era} 不在"


def test_seo_whitelist_includes_generic_descriptors():
    """promo / collection / anniversary 等 generic descriptor."""
    pool = _title_agent._UNIVERSAL_SEO_PERMITTED_TOKENS
    for tok in ["promo", "promos", "collection", "anniversary", "starter", "set"]:
        assert tok in pool, f"{tok} 不在"


def test_is_term_relevant_accepts_year_japanese_combo():
    """`2024 japanese` のような TOP 頻出 SEO 句が pass する (拒否されない)."""
    fn = _title_agent._is_term_relevant_to_franchise
    # franchise 'Pokemon TCG' で本カードキャラ 'Charizard'
    assert fn("2024 japanese", "Pokemon TCG", "Charizard") is True


def test_is_term_relevant_still_rejects_unsafe_tokens():
    """安全リスト外の単語 (例: 別キャラ名) は引き続き拒否 (副作用ゼロ確認)."""
    fn = _title_agent._is_term_relevant_to_franchise
    # 'pikachu' は別キャラ名なので本カード Charizard には追加させない
    # (ただし pikachu は franchise キャラなので pool 化、is_term... のロジックで別判定)
    # 確実にユニバーサル拒否される語: 'mtg' (別ゲーム) や 'random_word'
    assert fn("random_unrelated_word", "Pokemon TCG", "Charizard") is False
    assert fn("ascended heroes etb", "Pokemon TCG", "Charizard") is False


def test_existing_tokens_preserved():
    """既存の安全 tokens (holo, foil, tcg 等) が引き続き存在 (副作用ゼロ確認)."""
    pool = _title_agent._UNIVERSAL_SEO_PERMITTED_TOKENS
    for tok in ["holo", "foil", "1st", "edition", "tcg", "card", "rare", "alt", "art"]:
        assert tok in pool, f"既存 token {tok} が消えた"
