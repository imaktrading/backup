"""tests/test_mercari_description_extract - 商品説明 (H列) 抽出の回帰テスト.

2026-08-17 追加。 2026-08-15 のポーター走行で 56行の H列が全部空欄で入った事故の対策:
  - 説明は購入ボタンより遅れて描画されることがある → 出現を待つ
  - text が空でも textContent に入っていれば拾う
  - 待っても取れなければ description_missing=True で表に出す (silent 空欄 禁止)
"""
from __future__ import annotations

import pytest

from scrapers import mercari_item_detail as MID

pytestmark = pytest.mark.offline


class _MockElem:
    def __init__(self, text: str = "", text_content: str = ""):
        self._text = text
        self._tc = text_content

    @property
    def text(self) -> str:
        return self._text

    def get_attribute(self, name: str):
        return self._tc if name == "textContent" else None


class _MockDriver:
    """find_element が n 回目の呼出から要素を返すモック (遅れて描画される再現)."""

    def __init__(self, elem=None, appear_after: int = 0):
        self._elem = elem
        self._appear_after = appear_after
        self.calls = 0

    def find_element(self, by, selector):
        self.calls += 1
        if self._elem is None or self.calls <= self._appear_after:
            raise Exception("NoSuchElement")
        return self._elem


def test_description_immediately_available():
    d = _MockDriver(_MockElem(text="商品説明です"))
    assert MID._extract_description(d, wait_sec=0.0) == "商品説明です"


def test_description_appears_late_is_picked_up():
    """一発 find では取れないが、 待てば出るケース (= 事故の再現)."""
    d = _MockDriver(_MockElem(text="遅れて出た説明"), appear_after=5)
    assert MID._extract_description(d, wait_sec=2.0) == "遅れて出た説明"


def test_description_falls_back_to_text_content():
    """描画途中で .text が空でも textContent があれば拾う."""
    d = _MockDriver(_MockElem(text="", text_content="textContent の説明"))
    assert MID._extract_description(d, wait_sec=0.0) == "textContent の説明"


def test_description_absent_returns_empty():
    d = _MockDriver(None)
    assert MID._extract_description(d, wait_sec=0.2) == ""
