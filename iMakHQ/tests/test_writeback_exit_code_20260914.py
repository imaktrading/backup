"""itemID 書き戻しの終了コード: 書いて片付いたら 0 (2026-09-14).

🤖自動の締めで、出品直後の itemID を書き込んだのに毎回 returncode=1 と出ていた。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import itemid_writeback_audit as W  # noqa: E402


def test_written_leaks_are_success():
    assert W.writeback_exit_code(16, applied=True) == 0


def test_unwritten_leaks_are_not_silent():
    """検出のみ (--apply 無し) で漏れがあれば 1 のまま (正常と言わない)。"""
    assert W.writeback_exit_code(3, applied=False) == 1


def test_no_leaks_is_success():
    assert W.writeback_exit_code(0, applied=False) == 0
    assert W.writeback_exit_code(0, applied=True) == 0
