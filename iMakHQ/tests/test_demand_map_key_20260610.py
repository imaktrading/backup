# -*- coding: utf-8 -*-
"""Step6 P4: demand_map の PSA facet が canonical KEY 集計(番号衝突/heuristic排除)+ fallback."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import demand_map as dm


def test_extra_facets_psa_with_key_uses_canonical(monkeypatch):
    """KEY があれば ('KEY', product_id) + ('キャラ', catalog名) で集計(番号regex/heuristic不使用)。"""
    monkeypatch.setattr(dm, "_name_jp_for_key", lambda k: "サボ")
    out = dm.extra_facets("PSA card", "PSA10 Sabo OP10-049 alt art", key="OP10-049_p1")
    assert ("KEY", "OP10-049_p1") in out
    assert ("キャラ", "サボ") in out
    # 番号衝突しうる ('カード番号', ...) は出さない
    assert not any(kan == "カード番号" for kan, _ in out)


def test_extra_facets_psa_without_key_falls_back(monkeypatch):
    """KEY 未解決(管理外)→ 従来の番号regex + キャラheuristic。"""
    out = dm.extra_facets("PSA card", "PSA10 #OP13-004 Luffy alternate art", key=None)
    kans = {kan for kan, _ in out}
    assert "カード番号" in kans          # fallback で番号軸が出る
    assert "KEY" not in kans


def test_extra_facets_gshock_unchanged():
    out = dm.extra_facets("G-SHOCK", "Casio G-SHOCK GA-2100SB-1AJF", key=None)
    assert ("型番系統", "GA-2100") in out


def test_extra_facets_key_without_name_only_key(monkeypatch):
    """catalog name_jp が引けなくても KEY軸は出す(キャラ軸は無し)。"""
    monkeypatch.setattr(dm, "_name_jp_for_key", lambda k: None)
    out = dm.extra_facets("PSA card", "PSA10 OP01-001", key="OP01-001_p1")
    assert ("KEY", "OP01-001_p1") in out
    assert not any(kan == "キャラ" for kan, _ in out)
