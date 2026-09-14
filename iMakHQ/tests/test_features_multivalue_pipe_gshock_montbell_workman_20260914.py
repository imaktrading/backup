# -*- coding: utf-8 -*-
"""Features の複数値区切りを縦棒に統一 (2026-09-14, 残務 №17 の残り)。

TCG は 2026-08-25 に対応済 (test_features_multivalue_pipe_20260825.py)。
G-SHOCK / montbell / workman がまだ読点 ", " で繋いでいたので同じ直しを入れる。
eBay の Features は複数値フィールドなので縦棒 `|` で繋がないと 1 値の自由文になる
(実測: itemID 820035999901)。読点に戻ったら落ちるようにする回帰テスト。
"""
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


# ============================================================================
# G-SHOCK
# ============================================================================
_GSHOCK_DIR = os.path.join(_ROOT, "iMakG-shock")
if _GSHOCK_DIR not in sys.path:
    sys.path.insert(0, _GSHOCK_DIR)

try:
    _saved_argv = sys.argv
    sys.argv = ["gshock_to_csv.py"]
    import gshock_to_csv as G  # noqa: E402
    sys.argv = _saved_argv
    _GSHOCK_SRC = _read(os.path.join(_GSHOCK_DIR, "gshock_to_csv.py"))
except Exception as e:  # pragma: no cover
    G = None
    _GSHOCK_SRC = ""
    _GSHOCK_IMPORT_ERR = f"{type(e).__name__}: {e}"


def _require_gshock():
    if G is None:
        pytest.skip(f"gshock_to_csv import 不能: {_GSHOCK_IMPORT_ERR}")


def test_gshock_trim_features_joins_with_pipe_not_comma():
    _require_gshock()
    s = G.trim_features("bluetooth, tough_solar")
    assert "|" in s
    assert ", " not in s, "読点に戻ったら eBay は1値の自由文として持つ"


def test_gshock_normalize_features_accepts_pipe_input():
    _require_gshock()
    # catalog の古い値 (読点区切り) も、既に | 区切りに直した値も両方読める
    out_comma = set(G.normalize_features("bluetooth, tough_solar"))
    out_pipe = set(G.normalize_features("bluetooth|tough_solar"))
    assert out_comma == out_pipe
    assert "Bluetooth" in out_pipe


def test_gshock_get_features_joins_with_pipe():
    _require_gshock()
    s = G.get_features("Bluetooth搭載 タフソーラー")
    assert "|" in s or len(s.split("|")) >= 1
    assert ", " not in s


def test_gshock_source_uses_pipe_not_comma_join():
    """回帰: 4箇所とも読点結合に戻っていないか (実行せずソースで確認)。"""
    assert _GSHOCK_SRC, "gshock_to_csv.py が読めていない"
    assert 'candidate = "|".join(result + [p])' in _GSHOCK_SRC
    assert 'return "|".join(result)' in _GSHOCK_SRC
    assert 'return "|".join(features)' in _GSHOCK_SRC
    assert '"|".join(specs["features"]) if isinstance(specs.get("features"), list)' in _GSHOCK_SRC


def test_gshock_title_does_not_leak_separator():
    """build_title は features 文字列を部分一致でしか見ない → 区切り文字がタイトルに漏れない。"""
    _require_gshock()
    title = G.build_title("GA-2100-1A1JF", "Bluetooth|Tough Solar", "2026", False, "Digital", "Black")
    assert "|" not in title and ", " not in title


def test_gshock_description_features_shown_as_comma_list_not_raw_pipe():
    """説明文はバイヤーが読む自由文。C:Features 用の縦棒をそのまま出さない。"""
    _require_gshock()
    html = G.build_specs_html({"features": "Bluetooth|Tough Solar"})
    assert "<b>Features:</b> Bluetooth, " in html, html
    assert "Bluetooth|" not in html and "|Tough" not in html


# ============================================================================
# montbell
# ============================================================================
_MERCARI_DIR = os.path.join(_ROOT, "iMakMercari")
if _MERCARI_DIR not in sys.path:
    sys.path.insert(0, _MERCARI_DIR)

try:
    import montbell_listing as MB  # noqa: E402
except Exception as e:  # pragma: no cover
    MB = None
    _MB_IMPORT_ERR = f"{type(e).__name__}: {e}"


def test_montbell_features_joined_with_pipe():
    if MB is None:
        pytest.skip(f"montbell_listing import 不能: {_MB_IMPORT_ERR}")
    out = MB._merge_catalog_spec({}, {"features": ["Waterproof", "Breathable"]})
    assert out["Features"] == "Waterproof|Breathable"
    assert ", " not in out["Features"]


# ============================================================================
# workman
# ============================================================================
try:
    import workman_listing as WK  # noqa: E402
except Exception as e:  # pragma: no cover
    WK = None
    _WK_IMPORT_ERR = f"{type(e).__name__}: {e}"


def _workman_rec():
    return {
        "name_en": "Warm Fleece Jacket",
        "name_jp": u"あったかフリースジャケット",
        "specs": {
            "color_variants": [{"ebay_color": "Black", "image_url": "http://x/1.jpg"}],
            "size_variants": ["M"],
            "sku_matrix": [{"sku": "abc", "color": "Black", "size": "M"}],
            "price_jpy": 3000,
            "category_code": "",
            "features": ["Water Repellent", "Windproof"],
            "brand": "",
            "material_jp": "",
            "gender": "Men",
            "representative_hinban": "12345",
        },
    }


def test_workman_features_column_joined_with_pipe():
    if WK is None:
        pytest.skip(f"workman_listing import 不能: {_WK_IMPORT_ERR}")
    row = WK.build_parent_row(_workman_rec(), None)
    assert row is not None
    assert "Water Repellent|Windproof" in row
    assert "Water Repellent, Windproof" not in row


def test_workman_title_does_not_leak_pipe():
    if WK is None:
        pytest.skip(f"workman_listing import 不能: {_WK_IMPORT_ERR}")
    row = WK.build_parent_row(_workman_rec(), None)
    title = row[2]
    assert "|" not in title and ", " not in title
