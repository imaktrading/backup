"""取下げ・棚②: 途中で PC が落ちても、後始末漏れ・落とし過ぎが起きない (2026-09-24)。"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
import cull_end as CE                                          # noqa: E402

SRC = lambda n: open(os.path.join(HERE, "..", "tools", n), encoding="utf-8").read()  # noqa: E731


def test_end_on_ebay_calls_on_ok_per_success():
    seen = []
    replies = {"1": "<Ack>Success</Ack>", "2": "<Ack>Failure</Ack><LongMessage>x</LongMessage>",
               "3": "<Ack>Failure</Ack><LongMessage>has already been closed</LongMessage>"}
    ok, ng = CE.end_on_ebay([{"item_id": i} for i in "123"],
                            post_fn=lambda c, x, t: replies[x[8]], token_fn=lambda: "t",
                            on_ok=seen.append)
    assert ok == ["1", "3"] and seen == ["1", "3"] and ng[0][0] == "2"


def test_done_ledger_writeback_runs_first_in_both():
    assert "writeback_done_ledger()" in SRC("cull_end.py")
    s = SRC("shelf_evict.py")
    assert s.index("CE.writeback_done_ledger()") < s.index("listed = listed_today_amount()\n    if a.amount")


def test_already_ended_goes_through_sheet_cleanup():
    assert "CW.apply({r[\"item_id\"] for r in ended}, commit=True)" in SRC("cull_end.py")
    assert "CW.apply(ended_ids, commit=True)" in SRC("shelf_evict.py")


def test_shelf_records_amount_per_item():
    s = SRC("shelf_evict.py")
    assert "remember_evicted(amount_of.get(iid, 0))" in s
    assert "CE.end_on_ebay([{\"item_id\": i} for i in ids], on_ok=_on_ok)" in s
