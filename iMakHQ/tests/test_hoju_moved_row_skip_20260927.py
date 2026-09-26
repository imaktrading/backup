"""補URL③: itemID が変わった行だけ飛ばし、他は書く (2026-09-27)。

1件を手で 9999 にしただけで、確かめた13件が全部書かれなかった。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
from psa_hoju_fill import moved_target_indices  # noqa: E402


def _row(iid):
    r = [""] * 40
    r[1] = iid
    return r


def test_only_the_changed_row_is_flagged():
    fresh = [["h"] * 40, _row("820174276223"), _row("9999"), _row("820174199413")]
    targets = [{"row": 2, "itemID": "820174276223"},
               {"row": 3, "itemID": "820174276519"},
               {"row": 4, "itemID": "820174199413"}]
    assert moved_target_indices(targets, fresh) == {1}


def test_row_beyond_sheet_is_flagged():
    assert moved_target_indices([{"row": 9, "itemID": "1"}], [["h"] * 40]) == {0}
