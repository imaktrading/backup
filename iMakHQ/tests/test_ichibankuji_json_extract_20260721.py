# -*- coding: utf-8 -*-
"""ichibankuji Claude応答の JSON 抽出堅牢化の回帰テスト (2026-07-21)。

バグ: Claude が JSON の後に説明文を付けて返すと json.loads が 'Extra data: line N' で落ち、
その景品が丸ごと生成から脱落していた(Baki 宮本武蔵/愚地克巳 が間欠再発で脱落)。
対策: _extract_first_json で最初の JSON オブジェクトだけ raw_decode(末尾の余分は無視)。
"""
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "iMak_ichibankuji")))
from ichibankuji_to_csv import _extract_first_json  # noqa: E402


def test_trailing_explanation_ignored():
    """★本命: JSON の後に説明文(Extra data)があっても最初のオブジェクトを返す。"""
    s = '{"series_name_en":"Ichiban Kuji Baki","character":"Musashi"}\n\nこのJSONは説明です。'
    assert _extract_first_json(s) == {"series_name_en": "Ichiban Kuji Baki", "character": "Musashi"}


def test_code_fence_stripped():
    assert _extract_first_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_leading_and_trailing_text():
    assert _extract_first_json('ここに前書き\n{"a": 2}\n後書き') == {"a": 2}


def test_clean_json():
    assert _extract_first_json('{"a": 3, "b": "x"}') == {"a": 3, "b": "x"}


def test_no_json_raises():
    import pytest
    with pytest.raises(Exception):
        _extract_first_json("JSONがまったく無いテキスト")
