"""title_keyword_proposal.applicable_keywords の精度ガード回帰テスト (2026-06-04)。

精度原則 (CLAUDE.md): 虚偽キーワードは絶対NG。商品に真に当てはまる語 (全有意語が
現タイトルに既出) のみ採用し、他ブランド/キャラの高検索語は注入しないことを固定する。
"""
import importlib.util
import os

_SPEC = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "iMakHQ", "tools", "title_keyword_proposal.py"))
_spec = importlib.util.spec_from_file_location("title_keyword_proposal", _SPEC)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)
applicable = mod.applicable_keywords

# (rank, keyword) の上位語サンプル
KWS = [(4, "hello kitty"), (5, "pokemon plush"), (30, "dragon ball"),
       (17, "sanrio"), (3, "watch"), (22, "casio watch men"), (2, "rolex mens watch")]


def test_no_false_brand_injection_kuromi():
    """Kuromi(Sanrio)商品に pokemon/hello kitty は採用しない。sanrio のみ採用。"""
    title = "Sanrio Kuromi Dalmatian Outfit Mascot Plush Keychain White Japan"
    phrases = [ph.lower() for _, ph, _ in applicable(title, KWS)]
    assert "sanrio" in phrases
    assert "pokemon plush" not in phrases
    assert "hello kitty" not in phrases


def test_no_false_brand_injection_casio():
    """Casio に rolex は採用しない。watch は採用 (真に該当)。"""
    title = "CASIO G-SHOCK GAW-100B-7AJF Radio Wave Solar White Watch"
    phrases = [ph.lower() for _, ph, _ in applicable(title, KWS)]
    assert "watch" in phrases
    assert "rolex mens watch" not in phrases


def test_true_multiword_keyword_accepted():
    """全有意語が既出の複合語は採用 (dragon ball)。"""
    title = "S.H.Figuarts Frieza Final Form Dragon Ball Z Figure Bandai"
    phrases = [ph.lower() for _, ph, _ in applicable(title, KWS)]
    assert "dragon ball" in phrases


def test_demand_limited_returns_empty():
    """高検索語が一切当てはまらない低需要商品は空 (= タイトルで救えない)。"""
    title = "Anello Grande Shoulder Bag CABIN GTM0172Z A5 Water Repellent"
    assert applicable(title, KWS) == []


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
