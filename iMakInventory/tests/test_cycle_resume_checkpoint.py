"""巡回の途中再開 (2026-09-24 ADV 依頼 resume_after_crash).

PC が巡回の途中で落ちても、次に始まった時は確認済みの行を回さず続きから回す。
- 確認済みの行は回し直さない / 取下げ待ちに二重に積まない
- スプシ書込は全行分 (前回分 + 今回分) を1回
- 1周終わったら記録を消す
- 読めない・条件違い・古い記録は使わない (= 最初から)
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import monitor_listings as ML  # noqa: E402


class _Crash(BaseException):
    """PC が落ちた代わり (except Exception で拾われない)."""


class _FakeSheet:
    title = "fake-sheet"


class _FakeWS:
    title = "fake"
    id = 0
    row_count = 100


def _rows(n=6):
    return [{"row_index": 10 + i, "url": f"https://jp.mercari.com/shops/product/p{i}",
             "item_id": f"82000000000{i}", "title": f"t{i}", "current_sold": "",
             "current_n_jpy_str": "", "err_flag_prev": ""} for i in range(n)]


@pytest.fixture
def env(tmp_path, monkeypatch):
    for name in ("DECISION_LOG_DIR",):
        monkeypatch.setattr(ML, name, tmp_path)
    for name in ("PENDING_REVISE_FILE", "ACTION_REQUIRED_FILE", "ACTION_REQUIRED_RESOLVED_FILE",
                 "RESCUE_EVENTS_FILE", "CLEARED_BACKUPS_ARCHIVE", "PENDING_REVIVE_FILE",
                 "NEWLY_IN_STOCK_STATE_FILE", "SOLD_ROW_LISTED_SEEN_FILE"):
        monkeypatch.setattr(ML, name, tmp_path / getattr(ML, name).name)
    monkeypatch.setattr(ML, "_ledger_path", lambda p: p)
    monkeypatch.setattr(ML, "open_sheet_by_id", lambda sid: _FakeSheet())
    monkeypatch.setattr(ML, "get_listings_worksheet", lambda sh, gid=0: _FakeWS())
    monkeypatch.setattr(ML, "ensure_listings_err_header", lambda ws: False)
    monkeypatch.setattr(ML, "ensure_sold_at_header", lambda ws: False)
    monkeypatch.setattr(ML, "_kill_stale_scraper_chrome", lambda *a, **k: None)
    monkeypatch.setattr(ML, "create_mercari_driver", lambda *a, **k: object())
    monkeypatch.setattr(ML, "create_amazon_driver", lambda *a, **k: object())
    written = []

    def _write(ws, updates, **k):
        written.append(sorted(u["row_index"] for u in updates))
        return {"updated": len(updates)}

    monkeypatch.setattr(ML, "update_listings_sold_marks", _write)
    for fn in ("paint_backup_url_cells", "clear_sold_backup_cells", "append_rescue_log_rows"):
        monkeypatch.setattr(ML, fn, lambda *a, **k: {})
    return {"tmp": tmp_path, "written": written, "monkeypatch": monkeypatch}


def _run(env, rows, crash_at=None):
    env["monkeypatch"].setattr(
        ML, "read_listings_rows",
        lambda ws, start_row=None, end_row=None, only_with_url=True: [dict(r) for r in rows])
    scraped = []

    def _check(row, **kw):
        if crash_at is not None and len(scraped) == crash_at:
            raise _Crash()
        scraped.append(row["url"])
        sold = row["url"].endswith("p1")   # p1 だけ売切 = 取下げ待ちに積まれる
        return {"row_index": row["row_index"], "url": row["url"], "item_id": row["item_id"],
                "title": row["title"], "supplier": "mercari", "is_sold": sold,
                "raw_status": "SOLD_OUT" if sold else "ON_SALE", "current_sold": "",
                "delta": "newly_sold" if sold else "unchanged", "error": None,
                "price_jpy": 1000, "candidates_checked": 1, "current_n_jpy_str": "",
                "sub_results": []}

    env["monkeypatch"].setattr(ML, "check_one_row_with_fallback", _check)
    try:
        ML.process_sheet(sheet_id="sid", sheet_label="SHEET", dry_run=False, sleep_sec=0)
    except _Crash:
        pass
    return scraped


def _pending(env):
    p = env["tmp"] / "pending_revise.jsonl"
    return [json.loads(l)["item_id"] for l in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []


def test_resume_skips_checked_rows_and_writes_all(env):
    rows = _rows(6)
    first = _run(env, rows, crash_at=3)          # 3行確認したところで落ちる
    assert len(first) == 3 and env["written"] == []
    assert _pending(env) == ["820000000001"]     # 売切の p1 は確認時点で積まれている
    assert (env["tmp"] / "checkpoint_SHEET.jsonl").exists()

    second = _run(env, rows)
    assert second == [r["url"] for r in rows[3:]]           # 続きの3行だけ回す
    assert env["written"] == [[10, 11, 12, 13, 14, 15]]     # 書込は全6行を1回
    assert _pending(env) == ["820000000001"]                # 二重に積まない
    assert not (env["tmp"] / "checkpoint_SHEET.jsonl").exists()   # 1周終わったら消える

    third = _run(env, rows)                                  # 次の巡回は最初から
    assert len(third) == 6


def test_resume_follows_shifted_rows(env):
    rows = _rows(4)
    _run(env, rows, crash_at=2)
    shifted = [{"row_index": 5, "url": "https://jp.mercari.com/shops/product/new",
                "item_id": "999", "title": "挿入行", "current_sold": "",
                "current_n_jpy_str": "", "err_flag_prev": ""}] + [dict(r, row_index=r["row_index"] + 1) for r in rows]
    second = _run(env, shifted)
    assert set(second) == {shifted[0]["url"], rows[2]["url"], rows[3]["url"]}
    assert env["written"] == [[5, 11, 12, 13, 14]]           # 前回分も今の行番号で書く


def test_changed_row_is_rechecked(env):
    rows = _rows(3)
    _run(env, rows, crash_at=2)
    rows[0]["item_id"] = "changed"                           # 仕入元/itemID が変わった行は回し直す
    second = _run(env, rows)
    assert rows[0]["url"] in second and rows[1]["url"] not in second


@pytest.mark.parametrize("breakage", ["garbage", "old", "other_sheet"])
def test_unusable_checkpoint_starts_over(env, breakage):
    rows = _rows(4)
    _run(env, rows, crash_at=2)
    p = env["tmp"] / "checkpoint_SHEET.jsonl"
    lines = p.read_text(encoding="utf-8").splitlines()
    head = json.loads(lines[0])
    if breakage == "garbage":
        lines[0] = "{broken"
    elif breakage == "old":
        head["started"] = (datetime.now() - timedelta(hours=9)).isoformat(timespec="seconds")
        lines[0] = json.dumps(head)
    else:
        head["sheet_id"] = "another"
        lines[0] = json.dumps(head)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert len(_run(env, rows)) == 4


def test_torn_last_line_is_rechecked(env):
    rows = _rows(4)
    _run(env, rows, crash_at=3)
    p = env["tmp"] / "checkpoint_SHEET.jsonl"
    text = p.read_text(encoding="utf-8").rstrip("\n")
    p.write_text(text[:-10] + "\n", encoding="utf-8")        # 最後の行が書きかけ
    second = _run(env, rows)
    assert second == [rows[2]["url"], rows[3]["url"]]


def test_dry_run_and_partial_runs_do_not_use_checkpoint(env):
    rows = _rows(3)
    env["monkeypatch"].setattr(
        ML, "read_listings_rows",
        lambda ws, start_row=None, end_row=None, only_with_url=True: [dict(r) for r in rows])
    env["monkeypatch"].setattr(ML, "check_one_row_with_fallback", lambda row, **kw: {
        "row_index": row["row_index"], "url": row["url"], "item_id": row["item_id"],
        "title": "", "supplier": "mercari", "is_sold": False, "raw_status": "ON_SALE",
        "current_sold": "", "delta": "unchanged", "error": None, "price_jpy": 1,
        "candidates_checked": 1, "current_n_jpy_str": "", "sub_results": []})
    ML.process_sheet(sheet_id="sid", sheet_label="SHEET", dry_run=True, sleep_sec=0)
    ML.process_sheet(sheet_id="sid", sheet_label="SHEET", dry_run=False, limit=2, sleep_sec=0)
    assert not (env["tmp"] / "checkpoint_SHEET.jsonl").exists()
