"""売れた分の補充: 再出品した後、番号を書き戻す前に落ちても、押し直しで二重に再出品しない (2026-09-24)。"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
import sold_restock as R                                       # noqa: E402

SRC = open(os.path.join(HERE, "..", "tools", "sold_restock.py"), encoding="utf-8").read()


def test_ledger_round_trip(tmp_path):
    p = str(tmp_path / "l.json")
    assert R.relisted_to("111", p) == ""
    R.remember_relisted("111", "222", p)
    assert R.relisted_to("111", p) == "222"


def test_recorded_right_after_success_and_checked_before_send():
    i_check = SRC.index("_prev = relisted_to(target)")
    i_send = SRC.index('resp = fx.post(call, build_item_xml(target, price, profile)')
    i_rec = SRC.index("remember_relisted(target, new_id)")
    i_writeback = SRC.index("itemid_writeback_audit.py")
    assert i_check < i_send < i_rec < i_writeback
