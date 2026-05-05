"""montbell_listing.py の catalog 連携テスト (2026-05-05).

設計思想:
  Catalog Claude の name_en 完成 + 抽出くん S/T 列連携 (Phase 1d-2) に伴い、
  HQ 側 montbell_listing.py の「catalog HIT → name_en/色/サイズ 直接利用 / fail-closed」
  動作を永久保証する.

memory: バグ=テスト追加運用 / dual_gate_disagreement / completion_must_be_proven
"""
import os
import sys
from unittest.mock import patch

# iMakMercari を sys.path に追加 (test_montbell_whitelist.py と同じパターン)
_MERCARI = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "iMakMercari"))
sys.path.insert(0, _MERCARI)

from montbell_listing import (
    _normalize_color_to_ebay,
    _normalize_size_jp,
    _build_listing_from_catalog,
)

while _MERCARI in sys.path:
    sys.path.remove(_MERCARI)


# ============================================================================
# 色正規化 (catalog 突き合わせ + 辞書 fallback + 部分一致)
# ============================================================================
def test_normalize_color_catalog_direct_hit():
    """catalog color_variants["jp"] と完全一致 → catalog "en" 採用."""
    cv = [{"suffix": "BL", "jp": "ブルー", "en": "Blue"}, {"suffix": "BK", "jp": "ブラック", "en": "Black"}]
    assert _normalize_color_to_ebay("ブルー", cv) == "Blue"
    assert _normalize_color_to_ebay("ブラック", cv) == "Black"


def test_normalize_color_catalog_not_specified_skip():
    """catalog en="Not Specified" は採用しない (辞書 fallback へ)."""
    cv = [{"suffix": "MIST", "jp": "ミスト", "en": "Not Specified"}]
    # 辞書にも無いので空文字 (HQ 側で AI fallback)
    assert _normalize_color_to_ebay("ミスト", cv) == ""


def test_normalize_color_dictionary_fallback():
    """catalog 不一致時、辞書 _KATAKANA_TO_EBAY_COLOR で正規化."""
    assert _normalize_color_to_ebay("ネイビー", []) == "Blue"
    assert _normalize_color_to_ebay("カーキ", []) == "Green"
    assert _normalize_color_to_ebay("ワインレッド", []) == "Red"


def test_normalize_color_compound_priority():
    """部分一致は長いキー優先 (ライトグリーン > グリーン)."""
    # ライトグリーン は丸ごと辞書にある = 直接一致
    assert _normalize_color_to_ebay("ライトグリーン", []) == "Green"
    # 余計な前置きがあっても抽出される
    assert _normalize_color_to_ebay("メンズライトグリーン", []) == "Green"


def test_normalize_color_unknown():
    """辞書外なら空文字 (HQ 側 AI fallback の起点)."""
    assert _normalize_color_to_ebay("謎の色", []) == ""
    assert _normalize_color_to_ebay("", []) == ""


# ============================================================================
# サイズ正規化 (JP→US テーブル + 前置/括弧除去)
# ============================================================================
def test_normalize_size_jp_basic():
    """JP S/M/L/XL → US 変換."""
    assert _normalize_size_jp("S") == ("S", "XS")
    assert _normalize_size_jp("M") == ("M", "S")
    assert _normalize_size_jp("L") == ("L", "M")
    assert _normalize_size_jp("XL") == ("XL", "L")
    assert _normalize_size_jp("XXL") == ("XXL", "XL")


def test_normalize_size_jp_with_prefix():
    """メンズ / レディース / キッズ プレフィックス除去."""
    assert _normalize_size_jp("メンズM") == ("M", "S")
    assert _normalize_size_jp("レディースL") == ("L", "M")


def test_normalize_size_jp_with_suffix_or_paren():
    """「サイズ」サフィックス / 括弧の身長表記除去."""
    assert _normalize_size_jp("Lサイズ") == ("L", "M")
    assert _normalize_size_jp("L (90-100cm)") == ("L", "M")


def test_normalize_size_jp_unknown():
    """不明サイズは空文字."""
    assert _normalize_size_jp("") == ("", "")
    assert _normalize_size_jp("フリー") == ("", "")


# ============================================================================
# _build_listing_from_catalog: catalog HIT / fail-closed
# ============================================================================
def _make_target(**kwargs):
    """テスト用 target dict (デフォルト値)."""
    base = {
        "row": 100, "url": "https://jp.mercari.com/item/m12345",
        "title_jp": "モンベル U.L.ストレッチウインドジャケット M ブルー",
        "condition": "目立った傷や汚れなし",
        "price_jpy": "10000",
        "photo_urls": "https://example.com/img.jpg",
        "description": "モンベル U.L.ストレッチウインドジャケット ブルー M",
        "model": "1103219",
        "mercari_color": "ブルー",
        "mercari_size": "M",
    }
    base.update(kwargs)
    return base


def _make_catalog(name_en="U.L. Stretch Wind Jacket"):
    """テスト用 catalog_result dict (name_en パラメータ化)."""
    return {
        "product_id": "1103219",
        "name_jp": "U.L.ストレッチウインドジャケット",
        "name": "U.L.ストレッチウインドジャケット",
        "name_en": name_en,
        "specs": {
            "type": "Jacket", "style": "Windbreaker", "department": "Men",
            "color_variants": [{"suffix": "BL", "jp": "ブルー", "en": "Blue"}],
            "size_variants": ["S", "M", "L"],
            "image_urls": ["https://example.com/c_1103219_bl.jpg"],
        },
    }


def test_build_listing_catalog_hit_uses_name_en():
    """catalog HIT 時、title に catalog name_en がそのまま入る (AI 翻訳に依存しない)."""
    with patch("montbell_listing._extract_via_short_ai") as m_ai:
        m_ai.return_value = {
            "color": "Blue", "size_jp": "M", "size_us": "S",
            "condition_description": "Pre-owned. Excellent condition.",
        }
        result = _build_listing_from_catalog(_make_target(), _make_catalog(), "fake_key")
    assert result is not None
    assert "U.L. Stretch Wind Jacket" in result["title"], \
        f"title に catalog name_en 含まれない: {result['title']}"


def test_build_listing_catalog_name_en_null_returns_none():
    """catalog name_en が None → SKIP (fail-closed Precision 100%)."""
    with patch("montbell_listing._extract_via_short_ai") as m_ai:
        m_ai.return_value = {"color": "Blue", "size_jp": "M", "size_us": "S",
                             "condition_description": ""}
        result = _build_listing_from_catalog(_make_target(), _make_catalog(name_en=None), "fake_key")
    assert result is None, "catalog name_en NULL では SKIP するべき"


def test_build_listing_catalog_name_en_empty_returns_none():
    """catalog name_en が空文字 → SKIP."""
    with patch("montbell_listing._extract_via_short_ai") as m_ai:
        m_ai.return_value = {"color": "Blue", "size_jp": "M", "size_us": "S",
                             "condition_description": ""}
        result = _build_listing_from_catalog(_make_target(), _make_catalog(name_en=""), "fake_key")
    assert result is None, "catalog name_en 空文字でも SKIP するべき"


def test_build_listing_uses_mercari_color_over_ai():
    """target.mercari_color (S 列) が AI fallback より優先される."""
    target = _make_target(mercari_color="ブルー")
    with patch("montbell_listing._extract_via_short_ai") as m_ai:
        # AI は "Red" 返すが S 列の "ブルー" を優先するべき
        m_ai.return_value = {"color": "Red", "size_jp": "M", "size_us": "S",
                             "condition_description": ""}
        result = _build_listing_from_catalog(target, _make_catalog(), "fake_key")
    assert result is not None
    # catalog 直接一致で Blue が採用されているはず
    assert result["item_specifics"].get("Color") == "Blue", \
        f"S 列ブルー優先されず: {result['item_specifics'].get('Color')}"


def test_build_listing_uses_mercari_size_over_ai():
    """target.mercari_size (T 列) が AI fallback より優先される."""
    target = _make_target(mercari_size="L")
    with patch("montbell_listing._extract_via_short_ai") as m_ai:
        # AI は "M/S" 返すが T 列の "L" を優先するべき
        m_ai.return_value = {"color": "Blue", "size_jp": "M", "size_us": "S",
                             "condition_description": ""}
        result = _build_listing_from_catalog(target, _make_catalog(), "fake_key")
    assert result is not None
    # JP=L → US=M, title に "US M" "(JP L)" が入る
    assert "US M" in result["title"] and "(JP L)" in result["title"], \
        f"T 列 L 優先されず: {result['title']}"


def test_build_listing_falls_back_to_ai_when_st_empty():
    """S/T 列が空なら AI fallback が採用される (段階移行サポート)."""
    target = _make_target(mercari_color="", mercari_size="")
    with patch("montbell_listing._extract_via_short_ai") as m_ai:
        m_ai.return_value = {"color": "Green", "size_jp": "XL", "size_us": "L",
                             "condition_description": ""}
        result = _build_listing_from_catalog(target, _make_catalog(), "fake_key")
    assert result is not None
    assert result["item_specifics"].get("Color") == "Green"
    assert "US L" in result["title"] and "(JP XL)" in result["title"]
