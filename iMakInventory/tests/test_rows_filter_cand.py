# -*- coding: utf-8 -*-
"""出品済 (itemID あり) と 出品候補 (itemID 空) の巡回分離 (2026-09-19 ユーザー判断).

HIGH は出品済だけを 6h おきに見る。候補は CAND として 1日2回に落とす。
候補は eBay に出ていない = 取下げ対象が無いので、CAND が止まっても fail-OPEN にならない。
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _rows():
    return [
        {"row_index": 2, "item_id": "356700921169", "url": "https://jp.mercari.com/item/m1"},
        {"row_index": 3, "item_id": "",             "url": "https://jp.mercari.com/item/m2"},
        {"row_index": 4, "item_id": "  ",           "url": "https://jp.mercari.com/item/m3"},
        {"row_index": 5, "item_id": "820113988203", "url": "https://jp.mercari.com/item/m4"},
    ]


def _apply(rows, rows_filter):
    from monitor_listings import filter_rows_by_item_id
    return filter_rows_by_item_id(rows, rows_filter)


def test_listed_keeps_only_rows_with_item_id():
    got = _apply(_rows(), "listed")
    assert [r["row_index"] for r in got] == [2, 5]


def test_candidate_keeps_only_rows_without_item_id():
    """空白だけの itemID も候補扱い (= 出品されていない)."""
    got = _apply(_rows(), "candidate")
    assert [r["row_index"] for r in got] == [3, 4]


def test_all_keeps_everything():
    assert len(_apply(_rows(), "all")) == 4


def test_labels_map_to_expected_filter():
    from run_cycle import ROWS_FILTER_BY_LABEL
    assert ROWS_FILTER_BY_LABEL.get("SHEET") == "listed"
    assert ROWS_FILTER_BY_LABEL.get("HIGH") == "listed"
    assert ROWS_FILTER_BY_LABEL.get("CAND") == "candidate"
    # LOW は従来どおり全部見る (分ける実益が無い)
    assert ROWS_FILTER_BY_LABEL.get("LOW") is None


def test_listed_and_candidate_together_cover_every_row():
    """取りこぼしゼロ: どの行も必ずどちらか一方に入る (= 監視から消えない)."""
    rows = _rows()
    a = _apply(rows, "listed")
    b = _apply(rows, "candidate")
    assert len(a) + len(b) == len(rows)
    assert not ({r["row_index"] for r in a} & {r["row_index"] for r in b})


def test_unknown_filter_is_rejected():
    from monitor_listings import filter_rows_by_item_id
    with pytest.raises(ValueError):
        filter_rows_by_item_id(_rows(), "listedd")


def test_cand_uses_its_own_lock_when_profiles_are_dedicated(monkeypatch, tmp_path):
    """CAND は HIGH と同じスプシを指すので、label から別 lock を選べること."""
    import monitor_listings as ml
    import run_cycle as rc

    monkeypatch.setattr(ml, "_default_profile_dirs", lambda: ("m", "a"))
    monkeypatch.setattr(ml, "resolve_profile_dirs", lambda label: ("m_CAND", "a_CAND"))
    monkeypatch.setattr(rc, "DECISION_LOG_DIR", tmp_path)

    path = rc._set_active_lock("both", "HIGH_SHEET_ID", "CAND")
    assert path.name == ".cycle_CAND.lock"
    # HIGH は従来どおり共通 lock (= CAND と直列にならない設定ミスを防ぐ)
    assert rc._set_active_lock("both", "HIGH_SHEET_ID", "SHEET") == rc.LOCK_FILE


def test_cand_falls_back_to_shared_lock_without_dedicated_profiles(monkeypatch, tmp_path):
    """専用 profile が無い間は共有 lock = 直列 (Chrome 衝突を起こさない安全側)."""
    import monitor_listings as ml
    import run_cycle as rc

    monkeypatch.setattr(ml, "_default_profile_dirs", lambda: ("m", "a"))
    monkeypatch.setattr(ml, "resolve_profile_dirs", lambda label: ("m", "a"))
    monkeypatch.setattr(rc, "DECISION_LOG_DIR", tmp_path)

    assert rc._set_active_lock("both", "HIGH_SHEET_ID", "CAND") == rc.LOCK_FILE


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))


def test_crash_recorder_writes_reason_to_file(tmp_path, monkeypatch):
    """pythonw では stderr が無いので、落ちた理由をファイルに残せること (2026-09-19)."""
    import sys
    import run_cycle as rc

    monkeypatch.setattr(rc, "CRASH_LOG_PATH", tmp_path / "cycle_crash.log")
    old_hook = sys.excepthook
    try:
        rc._install_crash_recorder()
        try:
            raise RuntimeError("検証用の落下")
        except RuntimeError:
            sys.excepthook(*sys.exc_info())
    finally:
        sys.excepthook = old_hook

    body = (tmp_path / "cycle_crash.log").read_text(encoding="utf-8")
    assert "RuntimeError" in body and "検証用の落下" in body
    assert "巡回が落ちました" in body
