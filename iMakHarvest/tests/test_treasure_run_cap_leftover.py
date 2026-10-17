"""tests/test_treasure_run_cap_leftover - トレジャーハントの「候補が約N件で打ち切り」
「売れた数の多い順」「残した語を次回の先頭に積む」(2026-10-15 HQ依頼)。

`_run()` は網 (スプシ/API/Chrome) に依存するので、その周りを全部差し替えて検証する。
"""
from __future__ import annotations

import json
import types

import pytest

import run_harvest_mercari_treasure as R
import run_harvest_mercari_psa10 as psa10
import scrapers.mercari_search_api as mercari_search_api
import sheet_writer_mercari_search as swms
import sheet_writer_mercari_seller as swss
import run_marker
import scrapers._chrome_util as chrome_util

pytestmark = pytest.mark.offline

ROWS = [
    {"番号": "001/S-P", "和名": "少ない方", "売れた数": "3", "上限仕入れ値(円)": "10000"},
    {"番号": "002/S-P", "和名": "多い方", "売れた数": "50", "上限仕入れ値(円)": "10000"},
    {"番号": "003/S-P", "和名": "中くらい", "売れた数": "10", "上限仕入れ値(円)": "10000"},
]


@pytest.fixture(autouse=True)
def _stub_everything(monkeypatch, tmp_path):
    monkeypatch.setattr(R.treasure_keywords, "load_rows", lambda csv_path=None: ROWS)
    monkeypatch.setattr(psa10, "load_cost_sanity", lambda: {"max_jpy": 70000, "enabled": True})
    monkeypatch.setattr(swms, "load_keys_all_tabs", lambda sh: set())
    monkeypatch.setattr(swss, "open_seller_staging_sheet", lambda: object())
    monkeypatch.setattr(mercari_search_api, "ApiSearchClient",
                        lambda: types.SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(run_marker, "mark_started", lambda *a, **k: None)
    monkeypatch.setattr(run_marker, "mark_finished", lambda *a, **k: None)
    # ★既定は「前回クラッシュの印は無い」。 実機の debug/treasure_running.flag を読みに
    # 行かせない (2026-10-17 自動再開機能を足した時のテスト汚染防止)
    monkeypatch.setattr(run_marker, "check_stale", lambda *a, **k: None)
    monkeypatch.setattr(chrome_util, "kill_chrome_for_profile", lambda *a, **k: None)
    monkeypatch.setattr(chrome_util, "kill_orphan_chromedriver", lambda *a, **k: None)
    monkeypatch.setattr(R, "append_treasure_items", lambda items, known_keys=None: {
        "tab": R.TREASURE_TAB, "appended": len(items), "skipped_existing": 0, "input": len(items)})
    leftover = tmp_path / "leftover.json"
    monkeypatch.setattr(R, "LEFTOVER_PATH", leftover)
    return leftover


def test_keywords_sorted_by_sold_count_descending(monkeypatch):
    """売れた数の多い順に回す (指定語が無い時)."""
    seen = {}

    def _fake_collect(args, **kw):
        seen["keywords"] = list(args.keywords)
        return {"candidates": [], "unreadable": [], "by_keyword": {}, "processed_urls": [],
                "truncated": False}

    monkeypatch.setattr(psa10, "collect", _fake_collect)
    R.main(["--dry-run"])

    # 和名部分だけ見て順序を確認 (番号語も混ざるので和名を含む語で絞る)
    names_in_order = [k for k in seen["keywords"] if any(
        name in k for name in ("多い方", "中くらい", "少ない方"))]
    assert names_in_order.index("PSA10 多い方") < names_in_order.index("PSA10 中くらい")
    assert names_in_order.index("PSA10 中くらい") < names_in_order.index("PSA10 少ない方")


def test_leftover_written_when_truncated(monkeypatch, tmp_path):
    """打ち切ったら、detail処理が届かなかった語を控えに残す."""
    def _fake_collect(args, **kw):
        kws = list(args.keywords)
        # 全語5件ずつ見つかった体で、detail処理は最初の語の5件だけ届いた (= 以降は残る)
        by_keyword = {k: 5 for k in kws}
        return {"candidates": [], "unreadable": [], "by_keyword": by_keyword,
                "processed_urls": ["u"] * 5, "truncated": True}

    monkeypatch.setattr(psa10, "collect", _fake_collect)
    leftover_path = R.LEFTOVER_PATH
    R.main(["--dry-run"])

    saved = json.loads(leftover_path.read_text(encoding="utf-8"))
    # 1語目(最も売れた数が多い語)だけ回った扱い、残り5語は次回に積まれる
    assert len(saved["keywords"]) == 5
    assert "PSA10 多い方" not in saved["keywords"]


def test_search_crashed_keywords_go_to_leftover_front(monkeypatch, tmp_path):
    """🥕2026-10-16 HQ依頼: 検索で落ちた語は『回した語』から外し、残した語の先頭に積む."""
    def _fake_collect(args, **kw):
        kws = list(args.keywords)
        by_keyword = {k: 5 for k in kws if k != "PSA10 多い方"}
        return {"candidates": [], "unreadable": [], "by_keyword": by_keyword,
                "processed_urls": ["u"] * 10, "truncated": False,
                "search_crashed_keywords": ["PSA10 多い方"]}

    monkeypatch.setattr(psa10, "collect", _fake_collect)
    leftover_path = R.LEFTOVER_PATH
    R.main(["--dry-run"])

    saved = json.loads(leftover_path.read_text(encoding="utf-8"))
    assert saved["keywords"][0] == "PSA10 多い方"


def test_auto_resume_from_stale_marker_without_manual_flag(monkeypatch, tmp_path):
    """🥕2026-10-17 HQ依頼④: PCが落ちたら --resume-from-json を手で打たなくても
    次回の起動が印(treasure_running.flag)を見て自動で続きから入る."""
    stale_dump = tmp_path / "crashed.json"
    stale_dump.write_text(json.dumps({
        "candidates": [], "unreadable": [], "collect_reject": {},
        "processed_urls": [], "truncated": False,
        "by_keyword": {"PSA10 多い方": 5}, "collected_urls": [],
    }), encoding="utf-8")
    monkeypatch.setattr(run_marker, "check_stale",
                        lambda *a, **k: {"dump_path": str(stale_dump)})

    seen = {}

    def _fake_collect(args, dump_path=None, resume=None, **kw):
        seen["dump_path"] = dump_path
        seen["resume"] = resume
        return {"candidates": [], "unreadable": [], "by_keyword": {}, "processed_urls": [],
                "truncated": False}

    monkeypatch.setattr(psa10, "collect", _fake_collect)
    R.main(["--dry-run"])

    assert seen["dump_path"] == stale_dump
    assert seen["resume"]["by_keyword"] == {"PSA10 多い方": 5}


def test_no_auto_resume_when_marker_dump_missing(monkeypatch, tmp_path):
    """印はあるが dump ファイル自体が無い (消えた等) 時は、最初から走る (壊れた参照で落ちない)."""
    monkeypatch.setattr(run_marker, "check_stale",
                        lambda *a, **k: {"dump_path": str(tmp_path / "does_not_exist.json")})

    seen = {}

    def _fake_collect(args, dump_path=None, resume=None, **kw):
        seen["resume"] = resume
        return {"candidates": [], "unreadable": [], "by_keyword": {}, "processed_urls": [],
                "truncated": False}

    monkeypatch.setattr(psa10, "collect", _fake_collect)
    R.main(["--dry-run"])

    assert seen["resume"] is None


def test_leftover_reused_at_front_next_run(monkeypatch, tmp_path):
    """前回残した語が、次回の検索語の先頭に来る."""
    R.LEFTOVER_PATH.write_text(json.dumps(
        {"csv_path": str(R.treasure_keywords.CSV_PATH), "keywords": ["PSA10 少ない方"]}),
        encoding="utf-8")

    seen = {}

    def _fake_collect(args, **kw):
        seen["keywords"] = list(args.keywords)
        return {"candidates": [], "unreadable": [], "by_keyword": {}, "processed_urls": [],
                "truncated": False}

    monkeypatch.setattr(psa10, "collect", _fake_collect)
    R.main(["--dry-run"])

    assert seen["keywords"][0] == "PSA10 少ない方"
