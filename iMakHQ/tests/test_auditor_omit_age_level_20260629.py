# -*- coding: utf-8 -*-
"""csv_auditor: TCG の Age Level は意図的に削除済(CPSC)→「列が無い」SEO提案を出さない
回帰テスト (2026-06-29)。出すと CPSC 方針と矛盾し毎回ノイズ+誤再追加リスク。"""
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "tools")))
import csv_auditor as ca


_ASPECTS = {
    "Age Level": {"constraint": {"aspect_usage": "RECOMMENDED"}},
    "Card Name": {"constraint": {"aspect_usage": "RECOMMENDED"}},
}


def _patch(monkeypatch):
    monkeypatch.setattr(ca, "load_aspects", lambda project: _ASPECTS)


def test_tcg_age_level_absence_not_flagged(monkeypatch):
    _patch(monkeypatch)
    headers = ["*Title", "C:Game"]   # Age Level も Card Name も列なし
    notes = ca.ebay_aspect_findings(headers, [["t", "One Piece"]], "tcg")
    msgs = " ".join(m for _s, m in notes)
    assert "Age Level" not in msgs          # 抑制された
    assert "Card Name" in msgs              # 他の欠落は従来通り提案される


def test_non_tcg_age_level_still_flagged(monkeypatch):
    _patch(monkeypatch)
    headers = ["*Title"]
    notes = ca.ebay_aspect_findings(headers, [["t"]], "gshock")
    msgs = " ".join(m for _s, m in notes)
    assert "Age Level" in msgs              # 抑制は tcg のみ (他projectは従来通り)
