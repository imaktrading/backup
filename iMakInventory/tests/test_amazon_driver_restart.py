"""amazon driver 自動再起動 regression (2026-06-25).

bug: driver auto-restart は mercari 専用で、 amazon は driver セッション死 (InvalidSessionId) 後に
残り全行が盲目化していた。 2026-06-23 06:30 LOW cycle で amazon driver が死亡 → row418〜831
(396行) が 6 秒で全滅 = 1 cycle 盲目 (一過性で翌 cycle 回復したが、 持続したら mercari 297 連続
失敗事故と同型の fail-OPEN リスク)。

修正: (1) driver-dead 検知に "invalid session id" 追加。 (2) amazon も連続 crash 閾値で
create_amazon_driver 再起動。 (3) amazon 成功で counter リセット。
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import monitor_listings as m  # noqa: E402


def test_amazon_restart_threshold_exists():
    assert hasattr(m, "AMAZON_RESTART_THRESHOLD")
    assert isinstance(m.AMAZON_RESTART_THRESHOLD, int)
    assert m.AMAZON_RESTART_THRESHOLD >= 1


def test_invalid_session_id_is_treated_as_driver_dead():
    """driver-dead 検知に invalid session id が含まれる (= 再起動 trigger になる)."""
    src = (ROOT / "monitor_listings.py").read_text(encoding="utf-8")
    assert "invalid session id" in src, "invalid session id keyword が消えている"
    # amazon 再起動ブロックが存在する
    assert 'res["supplier"] == "amazon" and driver_dead' in src, \
        "amazon driver 再起動ブロックが消えている"


def _amazon_error_result(row, _err="InvalidSessionIdException: Message: invalid session id"):
    return {
        "row_index": row["row_index"],
        "url": row["url"],
        "item_id": row.get("item_id", ""),
        "title": row.get("title", ""),
        "supplier": "amazon",
        "is_sold": None,
        "raw_status": "",
        "current_sold": row.get("current_sold", ""),
        "delta": "uncertain",
        "error": _err,
        "price_jpy": None,
        "candidates_checked": 0,
        "current_n_jpy_str": "",
        "sub_results": [],
    }


def test_amazon_consecutive_invalid_session_triggers_restart(monkeypatch):
    """amazon 行が連続 InvalidSessionId で全滅 → AMAZON_RESTART_THRESHOLD で driver 再起動。

    create_amazon_driver が初期生成 + 再起動で 2 回以上呼ばれることを確認 (= 盲目化しない)。
    """
    n_rows = 7
    rows = [
        {"row_index": i, "url": f"https://www.amazon.co.jp/dp/B0TEST{i:05d}/",
         "item_id": f"id{i}", "title": f"t{i}", "current_sold": ""}
        for i in range(2, 2 + n_rows)
    ]

    # 外部 I/O 境界をすべて mock
    ws = MagicMock()
    ws.title = "listings"
    ws.id = 1
    ws.row_count = 100
    monkeypatch.setattr(m, "open_sheet_by_id", lambda *_a, **_k: MagicMock(title="sh"))
    monkeypatch.setattr(m, "get_listings_worksheet", lambda *_a, **_k: ws)
    monkeypatch.setattr(m, "ensure_listings_err_header", lambda *_a, **_k: False)
    monkeypatch.setattr(m, "read_listings_rows", lambda *_a, **_k: rows)
    monkeypatch.setattr(m, "_kill_stale_scraper_chrome", lambda *_a, **_k: None)
    monkeypatch.setattr(m, "update_listings_sold_marks",
                        lambda *_a, **_k: {"updated": 0, "d_writes": 0, "n_writes": 0,
                                           "o_writes": 0, "err_writes": 0})
    monkeypatch.setattr(m, "append_pending_revise", lambda *_a, **_k: None)
    monkeypatch.setattr(m.time, "sleep", lambda *_a, **_k: None)

    create_calls = {"n": 0}

    def fake_create_amazon_driver(*_a, **_k):
        create_calls["n"] += 1
        return MagicMock(name=f"amazon_driver_{create_calls['n']}")

    monkeypatch.setattr(m, "create_amazon_driver", fake_create_amazon_driver)
    # 全 amazon 行を InvalidSessionId で失敗させる
    monkeypatch.setattr(m, "check_one_row_with_fallback",
                        lambda row, **_k: _amazon_error_result(row))

    res = m.process_sheet("sheet_id_dummy", "TEST", dry_run=False)

    # 初期生成 1 + 再起動 >=1 = create_amazon_driver は 2 回以上呼ばれる
    assert create_calls["n"] >= 2, (
        f"amazon driver 再起動が発火していない (create 呼出 {create_calls['n']} 回) "
        f"= 盲目化したまま")
    # 全行処理しきる (早期 abort しない、 漏れ NG 原則)
    assert res["processed"] == n_rows
    assert res["errors"] == n_rows
