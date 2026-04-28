#!/usr/bin/env python3
"""catalog_localization 翻訳辞書 + 警告 whitelist テスト (2026-04-29 拡充).

iMakCatalog の lookup 戻り値を eBay US 向けに正規化する後処理 layer を検証する.
拡充内容:
  - attribute_en (One Piece TCG 公式 5 属性: Slash/Strike/Ranged/Special/Wisdom)
  - color compound (赤/緑/青/紫/黒/黄 等を動的 split 翻訳)
  - 警告 whitelist (EN フィールドのみ check、_jp/_official/_text/Notes 系は silent)
"""
from __future__ import annotations
import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

# iMakTCG のパスを通す (catalog_localization.py は iMakTCG/ にある)
_REPO_ROOT = Path(__file__).resolve().parent.parent
_TCG_ROOT = _REPO_ROOT / "iMakTCG"
if str(_TCG_ROOT) not in sys.path:
    sys.path.insert(0, str(_TCG_ROOT))

from catalog_localization import localize_catalog_record  # noqa: E402


def _localize_capture(record):
    """localize_catalog_record を呼び出し、(出力 record, stdout 文字列) を返す."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        out = localize_catalog_record(record)
    return out, buf.getvalue()


# ============================================================================
# Attribute (One Piece TCG 公式 5 種) 単独翻訳
# ============================================================================
def test_attribute_single_slash():
    out, _ = _localize_capture({"attribute_en": "斬"})
    assert out["attribute_en"] == "Slash"


def test_attribute_single_strike():
    out, _ = _localize_capture({"attribute_en": "打"})
    assert out["attribute_en"] == "Strike"


def test_attribute_single_ranged():
    out, _ = _localize_capture({"attribute_en": "射"})
    assert out["attribute_en"] == "Ranged"


def test_attribute_single_special():
    out, _ = _localize_capture({"attribute_en": "特"})
    assert out["attribute_en"] == "Special"


def test_attribute_single_wisdom():
    out, _ = _localize_capture({"attribute_en": "知"})
    assert out["attribute_en"] == "Wisdom"


# ============================================================================
# Attribute compound (動的 split 翻訳)
# ============================================================================
def test_attribute_compound_strike_special():
    out, _ = _localize_capture({"attribute_en": "打/特"})
    assert out["attribute_en"] == "Strike/Special"


def test_attribute_compound_slash_special():
    out, _ = _localize_capture({"attribute_en": "斬/特"})
    assert out["attribute_en"] == "Slash/Special"


def test_attribute_compound_special_wisdom():
    out, _ = _localize_capture({"attribute_en": "特/知"})
    assert out["attribute_en"] == "Special/Wisdom"


def test_attribute_already_english_passthrough():
    """既に EN 値が入っている場合は変更しない (Bandai EN data 由来)."""
    out, _ = _localize_capture({"attribute_en": "Slash/Special"})
    assert out["attribute_en"] == "Slash/Special"


# ============================================================================
# Color compound 動的 split 翻訳
# ============================================================================
def test_color_compound_six_colors():
    """6色 (赤/緑/青/紫/黒/黄) 動的 split — Bandai EN 公式値と一致."""
    out, _ = _localize_capture({"color_en": "赤/緑/青/紫/黒/黄"})
    assert out["color_en"] == "Red/Green/Blue/Purple/Black/Yellow"


def test_color_compound_two_colors_dynamic():
    """既存 dict にない 2 色 compound でも split 動作."""
    out, _ = _localize_capture({"color_en": "緑/青"})
    assert out["color_en"] == "Green/Blue"


def test_color_single_red():
    out, _ = _localize_capture({"color_en": "赤"})
    assert out["color_en"] == "Red"


# ============================================================================
# 警告 whitelist (EN フィールドのみ、_jp / _official 系は silent)
# ============================================================================
def test_warning_silent_for_jp_suffix_fields():
    """feature_jp / get_info_jp / set_name_official に JP 残存しても警告ゼロ."""
    record = {
        "name_en": "Monkey D. Luffy",
        "type_en": "Character",
        "color_en": "Red",
        "attribute_en": "Strike",
        "rarity_en": "L",
        "feature_jp": "超新星/麦わらの一味",
        "get_info_jp": "プロモーションカード",
        "set_name_official": "ブースターパック 神速の拳【OP-11】",
        "name_jp": "モンキー・D・ルフィ",
        "card_text_jp": "【ブロッカー】",
    }
    _out, log = _localize_capture(record)
    assert "翻訳未対応 JP 文字残存" not in log, (
        f"silent であるべき _jp/_official フィールドで警告が発火: {log!r}"
    )


def test_warning_fires_for_unknown_en_field():
    """name_en に未知の JP が残ると警告発火 (= 辞書追加要求)."""
    _out, log = _localize_capture({"name_en": "謎のキャラ", "type_en": "Character"})
    assert "翻訳未対応 JP 文字残存" in log
    assert "name_en" in log


def test_warning_does_not_fire_for_known_translations():
    """全 EN フィールドが翻訳成功した record では警告ゼロ."""
    record = {
        "name_en": "モンキー・D・ルフィ",   # → "Monkey D. Luffy"
        "type_en": "キャラクター",            # → "Character"
        "color_en": "赤",                     # → "Red"
        "attribute_en": "打",                 # → "Strike"
        "rarity_en": "Promo",                 # passthrough
        "card_id": "P-001",
    }
    _out, log = _localize_capture(record)
    assert "翻訳未対応 JP 文字残存" not in log, (
        f"全フィールド翻訳成功なのに警告発火: {log!r}"
    )


# ============================================================================
# Integration: 実 DB record を流して警告ゼロを保証
# ============================================================================
def test_real_db_records_zero_warnings_on_known_fields():
    """5,996 件の OP TCG record 全部に対し、EN whitelist 警告がゼロ件であることを確認.

    辞書漏れ検出の golden test. 新弾追加で未知 JP 値が来た場合に発覚する.
    """
    import json
    import sqlite3

    db_path = _REPO_ROOT / "iMakCatalog" / "db" / "products.sqlite"
    if not db_path.exists():
        # CI 等で DB がない場合は skip
        import pytest
        pytest.skip("iMakCatalog DB not present")

    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute(
        "SELECT name, name_jp, set_name, set_name_official, specs "
        "FROM products WHERE category='one_piece_tcg'"
    )
    warnings_total = 0
    warnings_by_field: dict[str, int] = {}
    for name, name_jp, set_name, set_name_official, specs_json in cur.fetchall():
        s = json.loads(specs_json) if specs_json else {}
        # iMakCatalog adapter (lookup_one_piece) が組み立てる record と同じ shape を構築
        record = {
            "name_en":       name or "",
            "name_jp":       name_jp or "",
            "type_en":       s.get("Card Type", ""),
            "color_en":      s.get("Color", ""),
            "attribute_en":  s.get("Attribute", ""),
            "rarity_en":     s.get("Rarity", ""),
            "feature_jp":    s.get("Type", ""),
            "get_info_jp":   set_name_official or "",
            "set_name_official": set_name_official or "",
            "set_name":      set_name or "",
            "card_text":     s.get("card_text", ""),
            "card_text_jp":  s.get("card_text_jp", ""),
        }
        _out, log = _localize_capture(record)
        if "翻訳未対応 JP 文字残存" in log:
            warnings_total += 1
            for line in log.splitlines():
                if "key=" in line:
                    # key='attribute_en' の形式から抽出
                    s_idx = line.find("key='") + 5
                    e_idx = line.find("'", s_idx)
                    if s_idx > 4 and e_idx > s_idx:
                        k = line[s_idx:e_idx]
                        warnings_by_field[k] = warnings_by_field.get(k, 0) + 1
    conn.close()

    # 既知の未翻訳キャラ名 (辞書未収録) が残る分を除いて、構造的な辞書漏れがゼロであることを期待.
    # name_en のみは「マイナーキャラの未収録」が許容されるが、type/color/attribute/rarity はゼロでなければならない.
    structural_fields = {"type_en", "color_en", "attribute_en", "rarity_en"}
    structural_warnings = sum(
        v for k, v in warnings_by_field.items() if k in structural_fields
    )
    assert structural_warnings == 0, (
        f"構造的辞書漏れ検出: {warnings_by_field}"
    )


# Standalone runner
if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    cases = [
        ("attribute 斬→Slash",  test_attribute_single_slash),
        ("attribute 打→Strike", test_attribute_single_strike),
        ("attribute 射→Ranged", test_attribute_single_ranged),
        ("attribute 特→Special", test_attribute_single_special),
        ("attribute 知→Wisdom", test_attribute_single_wisdom),
        ("attribute 打/特",     test_attribute_compound_strike_special),
        ("attribute 斬/特",     test_attribute_compound_slash_special),
        ("attribute 特/知",     test_attribute_compound_special_wisdom),
        ("attribute EN passthrough", test_attribute_already_english_passthrough),
        ("color 6色 compound",  test_color_compound_six_colors),
        ("color 2色 dynamic",   test_color_compound_two_colors_dynamic),
        ("color 単独 赤",       test_color_single_red),
        ("warning silent _jp/_official", test_warning_silent_for_jp_suffix_fields),
        ("warning fires for unknown", test_warning_fires_for_unknown_en_field),
        ("warning zero on full success", test_warning_does_not_fire_for_known_translations),
        ("integration 5996 records", test_real_db_records_zero_warnings_on_known_fields),
    ]
    fails = 0
    for name, fn in cases:
        try:
            fn()
            print(f"  ✓ {name}")
        except AssertionError as e:
            print(f"  ✗ FAIL: {name}: {e}")
            fails += 1
    if fails == 0:
        print(f"\n✅ All {len(cases)} catalog_localization tests passed.")
    else:
        print(f"\n❌ {fails} failed.")
        sys.exit(1)
