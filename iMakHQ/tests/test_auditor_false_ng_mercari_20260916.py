# -*- coding: utf-8 -*-
"""監査くん mercari の毎日のニセ NG 2種 (2026-09-16)。

① タイトル Navy / C:Color Blue を不一致にしていた (カタログの color_variants では同じ色)
② check_csv の「AI総合レビュー」節の ❌ 箇条書きを error に数えていた (9/15: 13件/13件が偽)
依頼書: hq/requests/2026-09-15_act_code_proposals_mercari.md 提案①②
"""
import os
import sys

_TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import csv_auditor as ca  # noqa: E402

_H = ["*Title", "C:Color"]


def test_official_color_name_in_title_matches_ebay_color(monkeypatch):
    monkeypatch.setattr(ca, "_COLOR_ALIAS_CACHE", {"blue": {"navy", "blue"}})
    row = ["One Piece Luffy UNIQLO UT Navy US S (JP M) NWT", "Blue"]
    assert ca.title_spec_consistency(_H, row, "mercari") == []


def test_real_color_mismatch_still_reported(monkeypatch):
    monkeypatch.setattr(ca, "_COLOR_ALIAS_CACHE", {"blue": {"navy", "blue"}})
    row = ["One Piece Luffy UNIQLO UT White US S (JP M) NWT", "Blue"]
    assert ca.title_spec_consistency(_H, row, "mercari")


def test_live_catalog_knows_navy_is_blue():
    ca._COLOR_ALIAS_CACHE = None
    assert "navy" in ca._catalog_color_aliases().get("blue", set())


_LOG = (
    "  ❌ エラー: 0件\n"
    "════════\n"
    "  🤖 AI総合レビュー\n"
    "════════\n"
    "- ❌ `Theme`（Anime / One Piece）未入力の可能性→要追加\n"
    "- ❌ `Character`フィールド→「Luffy」入力推奨\n"
    "════════\n"
    "  チェック完了\n"
    "════════\n"
)


def test_ai_review_bullets_are_not_errors():
    assert not any(s.startswith("error") for s in ca.scan_log_lines(_LOG))
    assert ca._signal_line_samples(_LOG) == []


def test_real_error_outside_ai_review_is_still_counted():
    txt = "Traceback (most recent call last):\n" + _LOG
    assert any(s.startswith("error") for s in ca.scan_log_lines(txt))
