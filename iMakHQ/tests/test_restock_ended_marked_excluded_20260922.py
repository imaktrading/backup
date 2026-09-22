"""再仕入れ①: 出品が終わっていて新規に回した行は RESTOCK対象外 に記録する (2026-09-22)。
記録しないと ① の残りに毎回数えられ、押すたびに同じ1件が出ていた (820000791249)。"""
import os

SRC = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools",
                        "psa_resource_gate.py"), encoding="utf-8").read()


def test_relisted_rows_are_marked_excluded():
    i = SRC.index("n = _append_new_listing_rows(_relist)")
    assert "_mark_restock_excluded(" in SRC[i:i + 1200]


def test_mark_skips_existing_itemids():
    assert "str(i) not in have" in SRC
