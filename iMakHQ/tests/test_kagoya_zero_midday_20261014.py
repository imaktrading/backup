"""補0本は15時過ぎにもう一度全部探す (2026-10-14 ユーザー「1日2回」→「15時は？」→「そだな」)。"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
import kagoya_offload as K  # noqa: E402


def test_due_only_after_15_and_once_a_day():
    assert not K.zero_midday_due({}, "2026-10-14", 14)
    assert K.zero_midday_due({}, "2026-10-14", 15)
    assert not K.zero_midday_due({"zero_mid_date": "2026-10-14"}, "2026-10-14", 16)
    assert K.zero_midday_due({"zero_mid_date": "2026-10-13"}, "2026-10-14", 16)


def test_cycle_calls_midday_before_urgent():
    src = open(os.path.join(HERE, "..", "tools", "kagoya_offload.py"), encoding="utf-8").read()
    i = src.index("def cycle():")
    body = src[i:]
    assert body.index("start_midday_zero(") < body.index("start_urgent_restock(cfg, st, today)")
