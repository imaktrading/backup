"""補URL③の入替ログは「外した URL」を出しているので、そう書く (2026-09-22 入れた方に読めた)。"""
import os

SRC = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools",
                        "psa_hoju_fill.py"), encoding="utf-8").read()


def test_swap_log_says_removed():
    assert "もっと安いのが5本そろったので外した" in SRC
