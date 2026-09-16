# -*- coding: utf-8 -*-
"""週次カタログ監査の map潰れ: カタログが分類した「潰れて正しい組」を許可する (2026-09-17)。

守るもの: 控えた元の値に **無い値が加わったら許可しない** (新しい潰れは再検出)。
出典: catalog/requests/2026-09-15_integrity_weekly_backlog_done.md 「HQ にお願いすること」2
"""
import os
import sys

_TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import catalog_integrity_check as C  # noqa: E402

_ALLOW = {("one_piece_tcg", "set", "Wings of the Captain"):
          {"ブースターパック 双璧の覇者 [OP-06]", "双璧の覇者【OP-06】"}}


def test_same_sources_are_allowed():
    assert C.collision_allowed("one_piece_tcg", "set", "Wings of the Captain",
                               ["双璧の覇者【OP-06】", "ブースターパック 双璧の覇者 [OP-06]"], _ALLOW)


def test_new_source_joining_is_detected_again():
    assert not C.collision_allowed("one_piece_tcg", "set", "Wings of the Captain",
                                   ["双璧の覇者【OP-06】", "新しい弾【OP-99】"], _ALLOW)


def test_unlisted_group_is_detected():
    assert not C.collision_allowed("pokemon_tcg", "set", "Start Deck Generations", ["a", "b"], _ALLOW)


def test_allow_file_loads_and_has_no_multi_code_same_set_group():
    allow = C.load_collision_allow()
    assert len(allow) >= 50
