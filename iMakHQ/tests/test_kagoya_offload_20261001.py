"""補URL探索を KAGOYA で回す (kagoya_offload) の純関数のテスト。

2026-10-01 ユーザー確定: 補0〜3本 (売り切れ防止) は毎日 / 補4〜5本 (入れ替え) は間隔を空ける /
空振り続きは家の夜の検索と同じ台帳で外す / 途中で落ちても続きから。
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import kagoya_offload as K  # noqa: E402

TODAY = "2026-10-01"


def _skip_dry(entry, today):
    return bool(entry and entry.get("skip"))


def test_needs_search_by_age():
    assert K.needs_search(None, TODAY, 1) is True
    assert K.needs_search({"date": TODAY, "mercari": {}}, TODAY, 1) is False
    assert K.needs_search({"date": "2026-09-30", "mercari": {}}, TODAY, 1) is True
    assert K.needs_search({"date": "2026-09-30", "mercari": {}}, TODAY, 2) is False
    assert K.needs_search({"date": "2026-09-29", "mercari": {}}, TODAY, 2) is True


def test_needs_search_when_mercari_failed_last_time():
    # 前回メルカリが取れていない (= mercari キーが無い) なら、日付が今日でも探す
    assert K.needs_search({"date": TODAY, "snkrdunk": {}}, TODAY, 1) is True


def test_needs_search_bad_date_searches():
    assert K.needs_search({"date": "??", "mercari": {}}, TODAY, 7) is True


def test_plan_job_order_and_cadence():
    fill = [{"itemID": "A"}, {"itemID": "B"}]
    restock = [{"itemID": "R"}, {"itemID": "A"}]           # A は補充側で既に入る → 二重にしない
    swap = [{"itemID": "S1"}, {"itemID": "S2"}]
    cache = {
        "B": {"date": TODAY, "mercari": {}},              # 今日済み → 外す
        "S1": {"date": "2026-09-30", "mercari": {}},      # 入れ替えは2日に1回 → 昨日なら外す
        "S2": {"date": "2026-09-29", "mercari": {}},      # 2日前 → 探す
    }
    out, c = K.plan_job(fill, swap, restock, cache, {}, TODAY, _skip_dry, swap_every=2)
    assert [t["itemID"] for t in out] == ["A", "R", "S2"]
    assert [t["kind"] for t in out] == ["fill", "restock", "swap"]
    assert c["fresh_skip"] == 2 and c["fill"] == 1 and c["restock"] == 1 and c["swap"] == 1


def test_plan_job_dry_skip():
    out, c = K.plan_job([{"itemID": "A"}, {"itemID": "B"}], [], [], {}, {"A": {"skip": 1}}, TODAY, _skip_dry)
    assert [t["itemID"] for t in out] == ["B"]
    assert c["dry_skip"] == 1


def test_done_item_ids_resume_ignores_broken_lines():
    lines = [json.dumps({"itemID": "A"}), "{broken", "", json.dumps({"itemID": "B"})]
    assert K.done_item_ids(lines) == {"A", "B"}


def test_has_candidate():
    assert K.has_candidate({"cands": [[1000, "u", "n"]]}, {}) is True
    assert K.has_candidate({}, {"available": True}) is True
    assert K.has_candidate(None, {"available": False}) is False


def test_search_running_in_detects_home_search_only():
    assert K.search_running_in(["python -u psa_hoju_fill.py search --limit=30"]) is True
    assert K.search_running_in(["python psa_hoju_fill.py search-restock --limit=0"]) is True
    assert K.search_running_in(["python psa_hoju_fill.py confirm --limit=20", None, ""]) is False
    assert K.search_running_in(["python kagoya_offload.py cycle"]) is False


def test_ut_due_every_three_days():
    assert K.ut_due(None, TODAY, 3) is True
    assert K.ut_due("2026-09-29", TODAY, 3) is False
    assert K.ut_due("2026-09-28", TODAY, 3) is True


def test_covered_today():
    assert K.covered_today({"covered": {"desc": TODAY}}, "desc", TODAY) is True
    assert K.covered_today({"covered": {"desc": "2026-09-30"}}, "desc", TODAY) is False
    assert K.covered_today({}, "desc", TODAY) is False


def test_done_item_ids_by_other_key():
    lines = [json.dumps({"url": "u1"}), json.dumps({"url": "u2"})]
    assert K.done_item_ids(lines, "url") == {"u1", "u2"}


def test_lock_is_free():
    assert K.lock_is_free(None, lambda p: True)
    assert K.lock_is_free({"owner": "X"}, lambda p: True)
    assert K.lock_is_free({"owner": "X", "pid": 5}, lambda p: False)       # 持ち主が死んでいる
    assert not K.lock_is_free({"owner": "X", "pid": 5}, lambda p: True)


def test_can_take_seat_by_free_memory():
    assert K.can_take_seat(1.2, 2.0) is True          # 2.0 - 1.2 = 0.8 >= 0.4
    assert K.can_take_seat(1.2, 1.5) is False         # 余裕が足りない
    assert K.can_take_seat(0.2, 0.7) is True          # 軽い仕事なら並べられる


def test_acquire_and_release_server_seat(tmp_path):
    d = str(tmp_path / "seats")
    assert K.acquire_server_seat("HQ", 1.2, d, free_gb=3.0) is True
    assert K.acquire_server_seat("HQ", 1.2, d, free_gb=3.0) is False              # 同じ仕事は二重に取らない
    assert K.acquire_server_seat("HARVEST", 1.2, d, free_gb=1.0) is False         # 空きが足りない
    assert K.acquire_server_seat("HARVEST", 1.2, d, free_gb=2.5) is True          # 空きがあれば並べる
    K.release_server_seat("HQ", d)
    assert not os.path.exists(os.path.join(d, "HQ.json"))
    with open(os.path.join(d, "HQ.json"), "w", encoding="utf-8") as f:            # 死んだ持ち主の席は取り直せる
        json.dump({"owner": "HQ", "pid": 999999}, f)
    assert K.acquire_server_seat("HQ", 1.2, d, free_gb=3.0, pid_alive=lambda p: False) is True
