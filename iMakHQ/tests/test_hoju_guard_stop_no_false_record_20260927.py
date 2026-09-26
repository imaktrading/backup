"""補URL③: 書込を止めた時に「既に5本ある」と記録せず、目視待ちも落とさない (2026-09-27)。

書込中止の13件 (補0本) が「既に安い補URLが5本ある」と記録され、次から画面に出なくなっていた。
"""
import os

SRC = open(os.path.join(os.path.dirname(__file__), "..", "tools", "psa_hoju_fill.py"),
           encoding="utf-8").read()


def test_no_effect_is_empty_when_write_stopped():
    i = SRC.index("_no_effect = (confirmed_but_nothing_written(")
    assert "if _guard_ok else [])" in SRC[i:i + 200]


def test_pending_not_consumed_when_write_stopped():
    assert "if _shown_pending and _guard_ok:" in SRC
