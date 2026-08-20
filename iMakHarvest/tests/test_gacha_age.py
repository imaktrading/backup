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


# --------------------------------------------------------------------------
# JAN を出さない店向け: 公式カタログの商品名で引く
# --------------------------------------------------------------------------
from gacha_age import normalize_name

_NAMES = [("リラックマ×チュッパチャプス マスコットスイング", "4582769916625000"),
          ("まったく別のシリーズ ますこっと", "1111111111111000")]
CATALOG = [(normalize_name(n), code, n) for n, code in _NAMES]


def test_find_by_title_matches_official_name(monkeypatch):
    import gacha_age
    monkeypatch.setattr(gacha_age, "fetch_catalog", lambda *a, **k: CATALOG)
    t = "【全5種コンプリートセット】リラックマ×チュッパチャプス マスコットスイング バンダイ ガチャ"
    assert gacha_age.find_by_title(t) == "4582769916625000"


def test_find_by_title_is_blank_when_no_official_name_matches(monkeypatch):
    """当たらなければ空。 部分一致で別商品の年齢を貼らない."""
    import gacha_age
    monkeypatch.setattr(gacha_age, "fetch_catalog", lambda *a, **k: CATALOG)
    assert gacha_age.find_by_title("まったく別の商品 全5種セット バンダイ") == ""
