# -*- coding: utf-8 -*-
"""PSA に画像が無い個体は「同じカードの別 cert の画像」を使う (2026-08-14)。

★実害: cert 102629645 (ボア・ハンコック OP07-038) は PSA 側に画像が無く
  (文字情報は取れるのに CardImageUrl が1つも存在しない)、**2日連続で除外**され、
  毎回 1枠を食っていた。取得失敗ではないので、走り直しても永久に取れない。

ユーザー確定: 別 cert の画像を使ってよい。商品説明に「証明番号が異なる個体が届くことが
ある」と明記しているため齟齬は生じない (Stock Photo 運用)。

固定する挙動:
  1. 対応表 (iMak_data/dedupe/psa_image_override.json) から代替 cert を引ける
  2. 表に無い cert は "" (勝手に代替しない)
  3. 表が壊れている/無い時も落ちない
  4. 生成側が代替を使い、どの cert から借りたかを記録する (CardImageFromCert)
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys

_TCG = r"C:\dev\iMak\iMakTCG"


def _mod():
    if _TCG not in sys.path:
        sys.path.insert(0, _TCG)
    spec = importlib.util.spec_from_file_location("psa_gen_sub_test",
                                                  os.path.join(_TCG, "psa_to_csv.py"))
    m = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(m)
    except SystemExit:
        pass
    return m


def test_override_table_has_the_known_case():
    m = _mod()
    assert m.psa_image_substitute("102629645") == "149777037"


def test_unknown_cert_gets_no_substitute():
    m = _mod()
    assert m.psa_image_substitute("999999999") == ""
    assert m.psa_image_substitute("") == ""
    assert m.psa_image_substitute(None) == ""


def test_broken_table_does_not_crash(monkeypatch, tmp_path):
    m = _mod()
    p = tmp_path / "broken.json"
    p.write_text("{ not json", encoding="utf-8")
    monkeypatch.setattr(m, "PSA_IMAGE_OVERRIDE_PATH", str(p))
    assert m.psa_image_substitute("102629645") == ""
    monkeypatch.setattr(m, "PSA_IMAGE_OVERRIDE_PATH", str(tmp_path / "no_such.json"))
    assert m.psa_image_substitute("102629645") == ""


def test_generator_records_where_the_image_came_from():
    src = open(os.path.join(_TCG, "psa_to_csv.py"), encoding="utf-8").read()
    assert "psa_image_substitute(cert_number)" in src
    assert "CardImageFromCert" in src, "どの cert から借りたかを残していない"


def test_override_entries_explain_themselves():
    """表の各行に「なぜ代替するのか」を書く (後から見て判断できるように)。"""
    with open(r"C:/dev/iMak_data/dedupe/psa_image_override.json", encoding="utf-8") as f:
        m = json.load(f)
    for cert, v in m.items():
        assert v.get("from_cert"), cert
        assert v.get("why"), f"{cert} に理由が無い"
