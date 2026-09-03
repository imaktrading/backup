# -*- coding: utf-8 -*-
"""End を送ったら、実物を読み直して照合する (2026-09-03)。

## 実害
画面に `[4/4] ✅ END 358723950677` と出て「OK 4 / NG 0」で終わったのに、
**その出品は落ちていなかった** (実測: 9/26まで Active のまま)。
実際に落ちたのは別の1件で、表示と実物が食い違っていた。

送信の戻り値を「成功」として信じると、売れる状態で残ったことに誰も気づかない
(グローバル規約: 状態変更は送信後に実状態を verify し、漏れは要対応として明示する)。

## fail-closed
状態が読めないものは「終わった」に入れない。黙って済ませない。
"""
import os
import sys

_HQ_TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
if _HQ_TOOLS not in sys.path:
    sys.path.insert(0, _HQ_TOOLS)

import shelf_evict as SE  # noqa: E402


def test_only_really_ended_counts_as_done():
    done, todo = SE.split_verified({"a": "Completed", "b": "Active"})
    assert done == ["a"]
    assert todo == [("b", "Active")]


def test_unreadable_is_not_treated_as_done():
    """読めなかったものを「終わった」にすると、生きたまま気づかれない。"""
    done, todo = SE.split_verified({"x": None})
    assert done == []
    assert todo == [("x", "読めない")]


def test_ended_variants_all_count():
    done, _ = SE.split_verified({"a": "Completed", "b": "Ended", "c": "CustomCode"})
    assert sorted(done) == ["a", "b", "c"]


def test_sender_verifies_before_reporting_done():
    """送信の戻り値をそのまま完了扱いにしていないこと。"""
    src = open(os.path.join(_HQ_TOOLS, "shelf_evict.py"), encoding="utf-8").read()
    i = src.index("ok, ng = CE.end_on_ebay(")
    assert "_verify_ended(ok)" in src[i:i + 1200], "送信後の照合が入っていない"
