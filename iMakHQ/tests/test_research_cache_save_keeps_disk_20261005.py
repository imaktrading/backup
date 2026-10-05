"""補URL の控え (psa_research_cache.json) を保存する時に、ディスクにだけある出品を消さない (2026-10-05)。

10/5 6:00〜13:06 に控えが 1,142件 → 今日の307件に消え、補URL③ が「未検索 363件」と誤って数えた。
読めなかった手が {} + 今日の結果 を保存しても、過去の分が残ることを確かめる。
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import psa_hoju_fill as H  # noqa: E402


def test_keep_disk_entries_new_wins():
    out = H.keep_disk_entries({"a": {"date": "new"}}, {"a": {"date": "old"}, "b": {"date": "old"}})
    assert out == {"a": {"date": "new"}, "b": {"date": "old"}}


def test_save_with_empty_load_keeps_old(tmp_path):
    p = str(tmp_path / "c.json")
    json.dump({"old1": {"date": "2026-10-04"}, "old2": {"date": "2026-10-03"}}, open(p, "w", encoding="utf-8"))
    H._save_cache({"today": {"date": "2026-10-05"}}, p)     # 読み損ねて {} から始めた手
    got = json.load(open(p, encoding="utf-8"))
    assert set(got) == {"old1", "old2", "today"}


def test_unreadable_disk_refuses_to_write(tmp_path, monkeypatch):
    p = str(tmp_path / "c.json")
    open(p, "w", encoding="utf-8").write("{壊れている")
    monkeypatch.setattr(H.time, "sleep", lambda s: None)
    with pytest.raises(RuntimeError):
        H._save_cache({"today": {}}, p)
    assert open(p, encoding="utf-8").read() == "{壊れている"


def test_no_file_writes(tmp_path):
    p = str(tmp_path / "c.json")
    H._save_cache({"x": {}}, p)
    assert json.load(open(p, encoding="utf-8")) == {"x": {}}
