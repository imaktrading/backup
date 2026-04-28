"""Regression: catalog_localization が ひらがな card_name を翻訳できること.

事故 (2026-04-29):
  cert 114060943 / EB01-057 Shirahoshi の CSV title 末尾に `しらほし` が leak.
  iMakCatalog の detail_JA_*.json は card_name="しらほし" (ひらがな) で
  保存されていたが、_CHARACTER_JP_EN 辞書は カタカナ "シラホシ" のみ登録。
  → 辞書 miss → name_en="しらほし" のまま psa_to_csv へ → refine_title が
  英語 title 末尾に重複検知できずに "しらほし" を append.

修正 (catalog_localization.py):
  _translate_character_name の dict lookup 前に ひらがな→カタカナ 正規化を挟む.
  (新ヘルパー: _hiragana_to_katakana)

このテストは ひらがな表記の card_name を辞書経由で英訳できることを物理ギブス化.
"""
from __future__ import annotations
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TCG = _REPO_ROOT / "iMakTCG"
if str(_TCG) not in sys.path:
    sys.path.insert(0, str(_TCG))


def test_hiragana_to_katakana_basic():
    """ひらがな範囲のみ変換、それ以外は素通り."""
    from catalog_localization import _hiragana_to_katakana
    assert _hiragana_to_katakana("しらほし") == "シラホシ"
    assert _hiragana_to_katakana("シラホシ") == "シラホシ"  # no-op
    assert _hiragana_to_katakana("Shirahoshi") == "Shirahoshi"  # 英字素通り
    assert _hiragana_to_katakana("光月おでん") == "光月オデン"  # 漢字+ひらがな mix
    assert _hiragana_to_katakana("") == ""


def test_translate_character_name_hiragana_shirahoshi():
    """しらほし (ひらがな) → Shirahoshi: cert 114060943 EB01-057 事故再発防止."""
    from catalog_localization import _translate_character_name
    assert _translate_character_name("しらほし") == "Shirahoshi"


def test_translate_character_name_katakana_unchanged():
    """シラホシ (カタカナ) → Shirahoshi: 既存挙動維持."""
    from catalog_localization import _translate_character_name
    assert _translate_character_name("シラホシ") == "Shirahoshi"


def test_translate_character_name_unknown_hiragana_passthrough():
    """辞書未登録 ひらがな → そのまま (上位レイヤで警告)."""
    from catalog_localization import _translate_character_name
    # 存在しないキャラ名想定. 翻訳できないので入力をそのまま返す
    assert _translate_character_name("あいうえお") == "あいうえお"


def test_localize_catalog_record_shirahoshi_full():
    """end-to-end: iMakCatalog 風 record を渡すと name_en が英訳される."""
    from catalog_localization import localize_catalog_record
    record = {
        "name_en": "しらほし",
        "type_en": "キャラクター",
        "color_en": "赤",
        "attribute_en": "特殊",
        "card_id": "EB01-057",
    }
    out = localize_catalog_record(record)
    assert out["name_en"] == "Shirahoshi", (
        f"name_en should be translated from ひらがな to English; got {out['name_en']!r}"
    )
    # 副作用: type_en/color_en の既存翻訳が壊れていないことも担保
    assert out["type_en"] == "Character"
    assert out["color_en"] == "Red"
