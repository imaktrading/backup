"""中間スプシから HIGH に足す件数を区切る (2026-10-05 ユーザー「200追加して」)。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

import treasure_to_high as TH  # noqa: E402


def test_pick_buyable_takes_only_buyable_up_to_limit():
    add = [(i, [f"u{i}"]) for i in range(2, 12)]
    got, skipped = TH.pick_buyable(add, 3, check=lambda u: u not in ("u2", "u4"))
    assert [i for i, _r in got] == [3, 5, 6] and skipped == 2
