"""中間スプシから HIGH に足す件数を区切る (2026-10-05 ユーザー「200追加して」)。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

import treasure_to_high as TH  # noqa: E402


def test_pick_buyable_takes_only_buyable_up_to_limit():
    add = [(i, [f"u{i}"]) for i in range(2, 12)]
    got, skipped = TH.pick_buyable(add, 3, check=lambda u: u not in ("u2", "u4"))
    assert [i for i, _r in got] == [3, 5, 6] and skipped == 2


def test_売り切れと分かった行だけ印の候補にする_20261011():
    add = [(2, ["u1"]), (3, ["u2"]), (4, ["u3"])]
    sold = []
    got, skipped = TH.pick_buyable(add, 5, check=lambda u: {"u1": True, "u2": False, "u3": None}[u], sold_rows=sold)
    assert [i for i, _r in got] == [2] and skipped == 2 and sold == [3]
