"""tests/test_gashapon_line - 公式の商品ラインを起点に仕入元を探す (2026-08-21 新設).

店を先に決める探し方では集まらない商品ライン (めじるしアクセサリー: 公式84商品が
楽天の12店にばらけ、1店あたり数商品) 向け。
"""
from __future__ import annotations

import pytest

from run_harvest_gashapon_line import official_products, title_matches

pytestmark = pytest.mark.offline


def test_title_matches_requires_full_official_name():
    o = "TOY STORY5 めじるしアクセサリー"
    assert title_matches(o, "【全5種コンプリートセット】TOY STORY5 めじるしアクセサリー バンダイ")
    # 記号・空白の差は吸収する
    assert title_matches(o, "TOY　STORY5めじるしアクセサリー 全5種セット")


def test_title_matches_rejects_other_products_in_the_same_series():
    """同じシリーズの別弾を掴まない (fail-closed)."""
    assert not title_matches("ドラゴンボール めじるしアクセサリー4",
                             "ドラゴンボール めじるしアクセサリー3 全5種セット")
    assert not title_matches("サマーウォーズ めじるしアクセサリー2",
                             "サマーウォーズ めじるしアクセサリー 全5種セット")


def test_title_matches_rejects_short_names():
    """短すぎる名前は誤爆するので通さない."""
    assert not title_matches("くじ", "ガシャポンくじ 全5種セット")


def test_official_products_filters_by_line(monkeypatch):
    import gacha_age
    monkeypatch.setattr(gacha_age, "fetch_catalog", lambda *a, **k: [
        ("x", "1111111111111000", "TOY STORY5 めじるしアクセサリー"),
        ("y", "2222222222222000", "ドラゴンボール カプセルフィギュア"),
    ])
    got = official_products("めじるし")
    assert got == [("TOY STORY5 めじるしアクセサリー", "1111111111111000")]
