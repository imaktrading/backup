# -*- coding: utf-8 -*-
"""Step6 P2: build_card_query が canonical KEY 駆動(catalog厳密引き)+ bare fallback の test."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import mercari_psa_resource as mp


def test_build_card_query_uses_key_meta(monkeypatch):
    """KEY があれば catalog 厳密引きの name_jp + 変種画像を使い、key/image を carry する。"""
    monkeypatch.setattr(mp, "card_meta_for_key",
                        lambda k: {"name_jp": "サボ", "image": "https://x/OP10-049_p1.png", "set": "BEST SELECTION"})
    monkeypatch.setattr(mp, "name_jp_for_card", lambda c: "ちがう名前")  # 使われないはず
    q = mp.build_card_query("PSA10 Sabo OP10-049", "OP10-049", key="OP10-049_p1")
    assert q["name_jp"] == "サボ"
    assert q["image"] == "https://x/OP10-049_p1.png"
    assert q["key"] == "OP10-049_p1"
    assert q["card_no"] == "OP10-049"
    assert q["kw"] == "PSA10 サボ OP10-049"


def test_build_card_query_fallback_without_key(monkeypatch):
    """KEY 無なら従来の bare card_no 経路(name_jp_for_card)に fallback、image は空。"""
    monkeypatch.setattr(mp, "name_jp_for_card", lambda c: "ナミ")
    q = mp.build_card_query("PSA10 Nami OP08-106", "OP08-106")
    assert q["name_jp"] == "ナミ"
    assert q["image"] == ""
    assert q["key"] == ""
    assert q["kw"] == "PSA10 ナミ OP08-106"


def test_build_card_query_fallback_when_catalog_miss(monkeypatch):
    """KEY 渡しても catalog 未収録(meta None)なら bare fallback。"""
    monkeypatch.setattr(mp, "card_meta_for_key", lambda k: None)
    monkeypatch.setattr(mp, "name_jp_for_card", lambda c: "ルフィ")
    q = mp.build_card_query("PSA10 OP01-001", "OP01-001", key="OP01-001_unknown")
    assert q["name_jp"] == "ルフィ"
    assert q["image"] == ""
    assert q["key"] == "OP01-001_unknown"   # key は carry(解決不能でも記録)


def test_build_card_query_no_card_no(monkeypatch):
    """card_no 抽出不可なら kw 空(従来挙動維持)。"""
    monkeypatch.setattr(mp, "name_jp_for_card", lambda c: None)
    q = mp.build_card_query("no number here", "")
    assert q["kw"] == ""
    assert q["card_no"] == ""
