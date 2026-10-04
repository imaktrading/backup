"""値段が大きく上がった出品を補優先の先頭に (2026-10-05 ユーザー「価格変動 大きいものは、優先的に補を探しに行かないとだめだよ」)。"""
import datetime
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

import price_jump_hoju as J  # noqa: E402
import psa_hoju_fill as H  # noqa: E402

MOVES = [{"item_id": "UP3", "old_usd": 224.98, "new_usd": 736.98, "ratio": 3.276},
         {"item_id": "UP1", "old_usd": 100, "new_usd": 150, "ratio": 1.5},
         {"item_id": "SMALL", "old_usd": 100, "new_usd": 140, "ratio": 1.4},
         {"item_id": "DOWN", "old_usd": 300, "new_usd": 123, "ratio": 0.41}]


def test_only_big_rises_in_ratio_order():
    got = J.pick_jumps(MOVES, "2026-10-05")
    assert [j["iid"] for j in got] == ["UP3", "UP1"]          # 下がった方は入れない (ユーザー「優先の意味が薄れる」)


def test_merge_keeps_three_days_without_duplicates():
    today = datetime.date(2026, 10, 5)
    old = [{"iid": "A", "date": "2026-10-03"}, {"iid": "B", "date": "2026-10-01"}, {"iid": "UP3", "date": "2026-10-04"}]
    got = J.merge(old, J.pick_jumps(MOVES, "2026-10-05"), today)
    assert [x["iid"] for x in got] == ["UP3", "UP1", "A"]


def test_refresh_from_revise_file(tmp_path, monkeypatch):
    mv, jp = tmp_path / "moves.json", tmp_path / "jump.json"
    J._save(str(mv), {"at": "2026-10-05T06:04:34+09:00", "items": MOVES})
    monkeypatch.setattr(J, "MOVES_PATH", str(mv))
    monkeypatch.setattr(J, "JUMP_PATH", str(jp))
    monkeypatch.setattr(J, "DAILY_LOG", str(tmp_path / "daily.jsonl"))   # 本物の記録に書かない
    assert J.load_jump_priority() == ["UP3", "UP1"]
    monkeypatch.setattr(J, "MOVES_PATH", str(tmp_path / "none.json"))  # リバイスくんのファイルが無くても前の分は読める
    assert J.load_jump_priority() == ["UP3", "UP1"]


def test_hoju_priority_puts_price_jumps_before_shelf(monkeypatch):
    import shelf_psa_rules as R
    monkeypatch.setattr(J, "load_jump_priority", lambda: ["J1", "S1"])
    monkeypatch.setattr(R, "load_hoju_priority", lambda: ["S1", "S2"])
    assert H.load_shelf_priority() == ["J1", "S1", "S2"]


def test_daily_count_is_logged(tmp_path, monkeypatch):
    mv, jp, lg = tmp_path / "moves.json", tmp_path / "jump.json", tmp_path / "daily.jsonl"
    J._save(str(mv), {"at": "2026-10-05T06:04:34+09:00", "items": MOVES})
    monkeypatch.setattr(J, "MOVES_PATH", str(mv))
    monkeypatch.setattr(J, "JUMP_PATH", str(jp))
    monkeypatch.setattr(J, "DAILY_LOG", str(lg))
    J.refresh()
    J.refresh()                                                 # 同じ朝の分は2回数えない
    import json
    rows = [json.loads(x) for x in lg.read_text(encoding="utf-8").splitlines()]
    assert rows == [{"date": "2026-10-05", "source_at": "2026-10-05T06:04:34+09:00", "min_ratio": 1.5,
                     "moves": 4, "picked": 2}]
