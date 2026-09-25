"""週次の整合性チェックの「未検証の印」は note の先頭か括弧の形だけ見る (2026-09-26)。

部分一致だと「変幻の仮面」の仮 / 「(REVIEW のまま残っていた)」を印と誤読していた。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
from catalog_integrity_check import is_unverified_note  # noqa: E402


def test_marker_at_start_or_bracketed_is_unverified():
    for note in ("要確認 eBay master 未照合", "REVIEW: 旧値", "仮", "推定：年から",
                 "2026-09 取込 [要確認]", "値は【仮】", "(REVIEW) 後で見る"):
        assert is_unverified_note(note), note


def test_words_inside_prose_are_not_markers():
    for note in ("拡張パック「変幻の仮面」 — eBay master の verbatim",
                 "旧値は master に無く (REVIEW のまま残っていた)、derive を是正",
                 "仮面ライダー", "", None):
        assert not is_unverified_note(note), note
