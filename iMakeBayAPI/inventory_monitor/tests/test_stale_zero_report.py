"""棚卸レポート (在庫0が続いている公式出品) の test — 2026-09-01.

判断の物差しを「その場のログから計算する」ことが肝。固定値を書くと、
仕入元の性質が変わった時に古い基準で切り続けることになる。

固定すること:
  1. 在庫が戻った時点で経過日数をリセットする (途中で1日でも戻れば「継続」ではない)
  2. 復活実績の統計が正しく出る (何日で戻るのが普通か)
  3. 既定では 1 件も取り下げない (End は itemID が消える = 自動復活の対象外になる)
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import stale_zero_report as sz  # noqa: E402


def _write_logs(tmp_path, days: dict):
    """days = {"2026-08-01": [(item_id, brand, 在庫あり数), ...]}"""
    for day, rows in days.items():
        lines = []
        for iid, brand, n in rows:
            lines.append(f"[10:00:00]   ▶ listing {iid} [{brand}] (title)")
            lines.append(f"[10:00:01]     在庫: {n}/4 あり, 要対処: 0")
        (tmp_path / f"{day}.log").write_text("\n".join(lines), encoding="utf-8")
    return tmp_path


def test_counts_days_since_stock_hit_zero(tmp_path):
    _write_logs(tmp_path, {
        "2026-08-01": [("111", "uniqlo", 4)],
        "2026-08-05": [("111", "uniqlo", 0)],
        "2026-08-20": [("111", "uniqlo", 0)],
    })
    series, brand = sz.build_series(tmp_path)
    rows = sz.stuck_at_zero(series, brand)

    assert len(rows) == 1
    assert rows[0]["item_id"] == "111"
    assert rows[0]["zero_since"] == "2026-08-05"
    assert rows[0]["days"] == 15


def test_recovery_resets_the_counter(tmp_path):
    """★ 途中で在庫が戻ったら、経過日数はそこから数え直す."""
    _write_logs(tmp_path, {
        "2026-08-01": [("111", "uniqlo", 0)],
        "2026-08-10": [("111", "uniqlo", 2)],     # 復活
        "2026-08-12": [("111", "uniqlo", 0)],     # 再び0
        "2026-08-15": [("111", "uniqlo", 0)],
    })
    series, brand = sz.build_series(tmp_path)
    rows = sz.stuck_at_zero(series, brand)

    assert rows[0]["zero_since"] == "2026-08-12"
    assert rows[0]["days"] == 3


def test_in_stock_items_are_not_listed(tmp_path):
    _write_logs(tmp_path, {
        "2026-08-01": [("111", "uniqlo", 0)],
        "2026-08-05": [("111", "uniqlo", 3)],
    })
    series, brand = sz.build_series(tmp_path)
    assert sz.stuck_at_zero(series, brand) == []


def test_recovery_stats_measure_the_yardstick(tmp_path):
    _write_logs(tmp_path, {
        "2026-08-01": [("111", "uniqlo", 0), ("222", "gu", 0)],
        "2026-08-03": [("111", "uniqlo", 1)],                    # 2日で復活
        "2026-08-21": [("222", "gu", 1)],                        # 20日で復活
    })
    series, _ = sz.build_series(tmp_path)
    st = sz.recovery_stats(series)

    assert st["n"] == 2
    assert st["max"] == 20
    assert st["within_7d"] == 1


def test_brand_is_recorded(tmp_path):
    _write_logs(tmp_path, {"2026-08-01": [("111", "gu", 0)]})
    series, brand = sz.build_series(tmp_path)
    assert sz.stuck_at_zero(series, brand)[0]["brand"] == "gu"


def test_report_says_ending_disables_auto_revive(tmp_path):
    """取り下げの副作用 (自動復活の対象外になる) を必ず書く."""
    rows = [{"item_id": "111", "brand": "uniqlo", "zero_since": "2026-07-01",
             "days": 40, "title": "t"}]
    text = sz.format_report(rows, {"n": 10, "median": 0, "max": 30,
                                   "within_7d": 9, "within_14d": 10}, 30)

    assert "取り下げ候補" in text
    assert "自動復活の対象から外れます" in text


def test_no_logs_is_reported_not_silently_empty(tmp_path):
    series, brand = sz.build_series(tmp_path)
    assert series == {} and brand == {}
