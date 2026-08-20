"""tests/test_gacha_age - バンダイ品の 対象年齢 チェック (2026-08-20)."""
from __future__ import annotations

import pytest

from gacha_age import MIN_AGE, is_too_young, parse_age

pytestmark = pytest.mark.offline

# 実際の gashapon ページはラベルと数字の間にタグが入る
REAL = '<dt class="ttl">対象年齢</dt><dd class="txt">15才以上</dd>'


def test_parse_age_across_tags():
    assert parse_age(REAL) == 15


def test_parse_age_none_when_absent():
    assert parse_age("<html><body>商品情報</body></html>") is None


@pytest.mark.parametrize("age,ng", [(15, False), (16, False), (3, True), (12, True), (14, True)])
def test_is_too_young(age, ng):
    assert is_too_young(age) is ng


def test_unknown_age_is_not_dropped():
    """読めない = 不明。 落とさず 目視に回す (HQ と分担合意済)."""
    assert is_too_young(None) is False
    assert MIN_AGE == 15
