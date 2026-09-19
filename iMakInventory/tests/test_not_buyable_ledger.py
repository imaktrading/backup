# -*- coding: utf-8 -*-
"""売切で消した補URL を、出品くんの「買えないURL」台帳へ登録する (2026-09-19 依頼).

台帳は出品くんも書くので、監視くんは **追記だけ**。既に載っている理由は上書きしない。
書けなくても巡回は止めない (台帳は出品側の都合で、取下げの正しさには影響しない)。
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from monitor_listings import register_not_buyable  # noqa: E402


def test_adds_new_urls(tmp_path):
    p = tmp_path / "not_buyable_urls.json"
    r = register_not_buyable(["https://a", "https://b"], why="売り切れ", path=p)
    assert r == {"added": 2, "already": 0, "error": None}
    data = json.loads(p.read_text(encoding="utf-8"))
    assert set(data) == {"https://a", "https://b"}
    assert data["https://a"]["why"] == "売り切れ"
    assert data["https://a"]["at"]


def test_does_not_overwrite_existing_reason(tmp_path):
    """出品くんが書いた理由を潰さない."""
    p = tmp_path / "l.json"
    p.write_text(json.dumps({"https://a": {"why": "オークション", "at": "2026-09-01T00:00:00"}}),
                 encoding="utf-8")
    r = register_not_buyable(["https://a", "https://b"], why="売り切れ", path=p)
    assert r["added"] == 1 and r["already"] == 1
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["https://a"]["why"] == "オークション"
    assert data["https://b"]["why"] == "売り切れ"


def test_keeps_entries_written_by_others(tmp_path):
    """読込→書戻しの間に他が足した分を消さない (同じ内容を2回足しても壊れない)."""
    p = tmp_path / "l.json"
    register_not_buyable(["https://a"], why="売り切れ", path=p)
    register_not_buyable(["https://b"], why="売り切れ", path=p)
    assert set(json.loads(p.read_text(encoding="utf-8"))) == {"https://a", "https://b"}


def test_empty_and_blank_urls_are_noop(tmp_path):
    p = tmp_path / "l.json"
    assert register_not_buyable([], why="x", path=p)["added"] == 0
    assert register_not_buyable(["", "   ", None], why="x", path=p)["added"] == 0
    assert not p.exists()


def test_duplicates_in_one_call_counted_once(tmp_path):
    p = tmp_path / "l.json"
    r = register_not_buyable(["https://a", "https://a"], why="売り切れ", path=p)
    assert r["added"] == 1


def test_broken_ledger_is_reported_not_overwritten(tmp_path):
    """形式が想定と違ったら、上書きせずエラーを返す (台帳を壊さない)."""
    p = tmp_path / "l.json"
    p.write_text("[1, 2, 3]", encoding="utf-8")
    r = register_not_buyable(["https://a"], why="売り切れ", path=p)
    assert r["added"] == 0 and r["error"]
    assert p.read_text(encoding="utf-8") == "[1, 2, 3]"


def test_unreadable_ledger_does_not_raise(tmp_path):
    p = tmp_path / "l.json"
    p.write_text("{ broken json", encoding="utf-8")
    r = register_not_buyable(["https://a"], why="売り切れ", path=p)
    assert r["added"] == 0 and r["error"]


def test_stale_lock_is_taken_over(tmp_path):
    """相手が lock を残して落ちても、60秒超なら置き去りとみなして進む."""
    p = tmp_path / "l.json"
    lock = p.with_suffix(p.suffix + ".lock")
    lock.write_text("", encoding="utf-8")
    os.utime(lock, (0, 0))      # 大昔の lock
    r = register_not_buyable(["https://a"], why="売り切れ", path=p, retries=3)
    assert r["added"] == 1
    assert not lock.exists()




def test_only_one_off_urls_should_be_registered():
    """再入荷する仕入元は台帳に載せない (載せると仕入元を永久に失う)."""
    from sheet_updater import is_one_off_url
    assert is_one_off_url("https://snkrdunk.com/apparels/816214/used/49647249")
    assert is_one_off_url("https://jp.mercari.com/item/m123")
    # メルカリShops は再入荷する = 載せてはいけない
    assert not is_one_off_url("https://jp.mercari.com/shops/product/ABC")
    assert not is_one_off_url("https://www.amazon.co.jp/dp/B0ABC")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
