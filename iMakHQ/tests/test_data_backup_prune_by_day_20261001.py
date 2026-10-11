"""毎朝のバックアップ: 古い zip は「日付で」14日分残す / 取り直せる物は入れない (2026-10-01)。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import data_backup as D  # noqa: E402


def test_prune_counts_days_not_files():
    names = ["iMak_daily_20260929_0604.zip", "iMak_daily_20260930_0500.zip",
             "iMak_daily_20260930_0625.zip", "iMak_daily_20260930_0756.zip",
             "iMak_daily_20261001_0600.zip", "other.txt"]
    # ★2026-10-12: 残す日も1日1本 (その日の一番新しい物)
    assert D.zips_to_prune(names, keep=2) == ["iMak_daily_20260929_0604.zip", "iMak_daily_20260930_0500.zip",
                                              "iMak_daily_20260930_0625.zip"]
    assert D.zips_to_prune(names, keep=3) == ["iMak_daily_20260930_0500.zip", "iMak_daily_20260930_0625.zip"]


def test_recreatable_files_are_excluded():
    assert "_symbols" in D.EXCLUDE_DIRS
    assert D._excluded_file("HWiNFO_log_20260930.CSV", 1000)


def test_作業用の写しはバックアップに入れない_20261012():
    assert D._excluded_dir(r"hq\offload_work")
    assert D.KEEP == 7
