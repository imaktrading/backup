"""mercari driver の再起動は、その巡回の profile を使い続ける (2026-09-24).

旧: 予防再起動 / 連続失敗後の再起動が profile_dir を渡さず、LOW / CAND も再起動後は
HIGH の既定 profile を開いていた。HIGH と重なる時間帯 (07:30〜 / 14:45〜) に同じ profile を
2つの Chrome が掴んで起動に失敗しうる。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import monitor_listings as ML  # noqa: E402


class _FakeSheet:
    title = "fake-sheet"


class _FakeWS:
    title = "fake"
    id = 0
    row_count = 10


def _patch_common(monkeypatch, rows, fake_check):
    monkeypatch.setattr(ML, "open_sheet_by_id", lambda sid: _FakeSheet())
    monkeypatch.setattr(ML, "get_listings_worksheet", lambda sh, gid=0: _FakeWS())
    monkeypatch.setattr(ML, "read_listings_rows",
                        lambda ws, start_row=None, end_row=None, only_with_url=True: rows)
    monkeypatch.setattr(ML, "check_one_row_with_fallback", fake_check)
    monkeypatch.setattr(ML, "_kill_stale_scraper_chrome", lambda *a, **k: None)
    monkeypatch.setattr(ML, "create_amazon_driver", lambda *a, **k: object())


def test_preventive_restart_uses_label_profile(monkeypatch):
    rows = [{"row_index": 10 + i, "url": f"https://jp.mercari.com/item/m1234567890{i}",
             "item_id": "", "title": "t", "current_sold": "",
             "current_n_jpy_str": "", "err_flag_prev": ""} for i in range(3)]

    def _fake_check(row, **kwargs):
        return {"row_index": row["row_index"], "url": row["url"], "item_id": "",
                "supplier": "mercari", "is_sold": False, "raw_status": "ON_SALE",
                "current_sold": "", "delta": "unchanged", "error": None, "price_jpy": 1000,
                "candidates_checked": 1, "current_n_jpy_str": "", "sub_results": []}

    _patch_common(monkeypatch, rows, _fake_check)
    calls = []

    class _D:
        def quit(self):
            pass

    def _create(*a, **k):
        calls.append(k.get("profile_dir"))
        return _D()

    monkeypatch.setattr(ML, "create_mercari_driver", _create)
    monkeypatch.setattr(ML, "MERCARI_PREVENTIVE_RESTART_EVERY", 1)
    monkeypatch.setattr(ML, "set_active_profile_dirs", lambda label: ("C:/p/mercari_LOW", "C:/p/amazon_LOW"))
    ML.process_sheet(sheet_id="dummy", sheet_label="TEST", dry_run=True)

    assert len(calls) >= 2, calls           # 初回起動 + 予防再起動
    assert set(calls) == {"C:/p/mercari_LOW"}, calls
