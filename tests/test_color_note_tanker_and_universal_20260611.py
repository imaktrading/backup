# -*- coding: utf-8 -*-
"""色見え注記の回帰テスト (2026-06-11)。

2026-06-09 Oskar(デンマーク) Porter Tanker 色見えクレーム対応:
- ① 汎用 "About Color" 注記を全カテゴリ Description テンプレに収録 (照明/カメラで色が違って見えるのは全商品共通)。
- ② Porter Tanker のみ ballistic nylon 固有注記を上乗せ (黒→灰の acute 誤認)。
"""
import importlib.util
import os

import pytest

_MERCARI = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "iMakMercari", "mercari_to_ebay_csv.py"))
_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))

# ① 汎用注記を持つべき全テンプレ
_UNIVERSAL_TEMPLATES = [
    "iMakMercari/USED.txt", "iMakMercari/NEW.txt", "iMakMercari/NEW_workman.txt",
    "iMakTCG/PSA10.txt", "iMakTCG/PSA10_snkrdunk.txt",
    "iMakG-shock/GSHOCK.txt", "iMak_ichibankuji/ICHIBANKUJI.txt",
]


@pytest.fixture(scope="module")
def m():
    # mercari_to_ebay_csv は import 時に相対パス "API key.txt" を開くため、当該 dir で import
    prev = os.getcwd()
    os.chdir(os.path.dirname(_MERCARI))
    try:
        spec = importlib.util.spec_from_file_location("mercari_to_ebay_csv_colornote", _MERCARI)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        os.chdir(prev)
    return mod


# ---- ① 汎用 About Color 注記 (全テンプレ) ----
@pytest.mark.parametrize("rel", _UNIVERSAL_TEMPLATES)
def test_universal_color_note_in_all_templates(rel):
    t = open(os.path.join(_ROOT, rel), encoding="utf-8").read()
    assert "About Color" in t, f"{rel} に汎用色注記が無い"
    assert "lighting, camera, and screen settings" in t


# ---- ② Tanker 固有注記 ----
def test_tanker_note_only_for_porter_tanker(m):
    note = m.tanker_color_note("Porter", "YOSHIDA PORTER Tanker Shoulder Bag S Black Used Japan")
    assert "ballistic nylon" in note
    # 非Tanker Porter → 注記なし
    assert m.tanker_color_note("Porter", "YOSHIDA PORTER Heat Waist Bag Black Used Japan") == ""
    # 別カテゴリ → 注記なし
    assert m.tanker_color_note("リール", "Shimano Tanker Reel") == ""
    # 空 → 注記なし
    assert m.tanker_color_note(None, None) == ""


def test_build_description_includes_extra_note(m, tmp_path):
    tpl = tmp_path / "t.txt"
    tpl.write_text(
        '<html><body><p>X</p>'
        '<p><span style="text-decoration: underline;"><strong>Shipping</strong></span></p>'
        '</body></html>', encoding="utf-8")
    note = m.TANKER_COLOR_NOTE
    out = m.build_description_with_specs(str(tpl), {"Brand": "Porter"}, extra_note_html=note)
    assert "ballistic nylon" in out
    # 注記は Specs の後・Shipping の前
    assert out.index("Specifications") < out.index("ballistic nylon") < out.index("Shipping")
    # extra_note 無し (後方互換) は注記が入らない
    out2 = m.build_description_with_specs(str(tpl), {"Brand": "Porter"})
    assert "ballistic nylon" not in out2


def test_porter_tanker_full_description_has_both_notes(m):
    """Porter Tanker の実テンプレ(USED.txt)出力に ①汎用 と ②Tanker 両方が入る。"""
    tpl = os.path.join(_ROOT, "iMakMercari", "USED.txt")
    note = m.tanker_color_note("Porter", "YOSHIDA PORTER Tanker Shoulder Bag S Black Used Japan")
    out = m.build_description_with_specs(tpl, {"Brand": "Porter", "Color": "Black"}, extra_note_html=note)
    assert "About Color" in out            # ① 汎用(テンプレ由来)
    assert "ballistic nylon" in out        # ② Tanker 上乗せ
