# -*- coding: utf-8 -*-
"""定期処理の点検の知らせは、回答済みの日の依頼書に足さず _2, _3 に書く (2026-10-15 ブラボー)。

10/15 の hq と revise で、_response のある 2026-10-15_schedule_audit.md に 03:00 / 09:00 の分を足していた
(置き場では済んだ扱いで配られない)。ut_identify の 2263f85a と同じ形。
"""
import datetime
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import schedule_audit as SA  # noqa: E402

NOW = datetime.datetime(2026, 10, 15, 9, 0)


def test_unanswered_same_day_file_is_reused(tmp_path):
    (tmp_path / "2026-10-15_schedule_audit.md").write_text("x", encoding="utf-8")
    assert os.path.basename(SA.request_path(str(tmp_path), NOW)) == "2026-10-15_schedule_audit.md"


def test_answered_file_moves_to_next_number(tmp_path):
    for f in ("2026-10-15_schedule_audit.md", "2026-10-15_schedule_audit_response.md",
              "2026-10-15_schedule_audit_2.md", "2026-10-15_schedule_audit_2_processed.md"):
        (tmp_path / f).write_text("x", encoding="utf-8")
    assert os.path.basename(SA.request_path(str(tmp_path), NOW)) == "2026-10-15_schedule_audit_3.md"
