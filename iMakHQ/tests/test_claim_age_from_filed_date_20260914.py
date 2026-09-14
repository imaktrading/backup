"""残務ボードの「N日前」と並び順は起票日で決める (2026-09-14).

進捗を追記しただけで 20日前の件が「9分前」になり、P1 の順番も後ろにずれた。
"""
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import claim as C  # noqa: E402


def test_filed_date_wins_over_file_time(tmp_path):
    p = tmp_path / "2026-08-25_x.md"
    p.write_text("# 件名\n\n- 優先度: 2\n- 起票: 2026-08-25 07:13 [出品専任]\n\n本文\n", encoding="utf-8")
    with open(p, "a", encoding="utf-8") as f:
        f.write("\n## 追記 今日\n")
    it = C._parse_backlog(p)
    assert it["mtime"] == datetime(2026, 8, 25, 7, 13).timestamp()
    assert it["mtime"] < time.time() - 86400


def test_date_only_and_missing_fall_back(tmp_path):
    assert C.filed_ts("- 起票: 2026-09-01\n", 1.0) == datetime(2026, 9, 1).timestamp()
    assert C.filed_ts("起票の行なし", 123.0) == 123.0


def test_appending_does_not_reorder_same_priority(tmp_path):
    old = tmp_path / "a.md"
    new = tmp_path / "b.md"
    old.write_text("# 古い\n- 優先度: 1\n- 起票: 2026-09-03 19:09 [x]\n", encoding="utf-8")
    new.write_text("# 新しい\n- 優先度: 1\n- 起票: 2026-09-14 16:09 [x]\n", encoding="utf-8")
    with open(old, "a", encoding="utf-8") as f:
        f.write("\n## 追記\n")
    items = sorted([C._parse_backlog(new), C._parse_backlog(old)], key=lambda it: it["mtime"])
    assert [it["title"] for it in items] == ["古い", "新しい"]
