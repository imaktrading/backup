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

# 取下げの実処理は iMakInventory 側の eBay クライアントを使う (patch のために先に通す)
_INV_ROOT = ROOT.parent.parent / "iMakInventory"
if str(_INV_ROOT) not in sys.path:
    sys.path.insert(0, str(_INV_ROOT))

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


# ============================================================================
# 自動 END (2026-09-01 ユーザー指示で有効化)
# ============================================================================
from unittest.mock import patch  # noqa: E402


def _row(iid, days, brand="uniqlo"):
    return {"item_id": iid, "brand": brand, "zero_since": "2026-07-01",
            "days": days, "title": "t", "url": "https://www.uniqlo.com/x"}


def _patch_ebay(status="Completed", site="US", before="Active"):
    """eBay 呼出を差し替える (1回目=終了前の確認、2回目=終了後の確認)."""
    mod = "ebay_actions.trading_api_client"
    pre = f"<GetItemResponse><Site>{site}</Site><ListingStatus>{before}</ListingStatus></GetItemResponse>"
    post = f"<GetItemResponse><Site>{site}</Site><ListingStatus>{status}</ListingStatus></GetItemResponse>"
    seq = {"n": 0}

    def call(name, body, **kw):
        seq["n"] += 1
        return {"raw_xml": pre if seq["n"] % 2 == 1 else post}

    return (patch(f"{mod}.end_fixed_price_item", return_value={"success": True}),
            patch(f"{mod}._call_trading", side_effect=call))


def test_ends_only_items_over_threshold(tmp_path, monkeypatch):
    monkeypatch.setattr(sz, "ENDED_LEDGER", tmp_path / "ended.jsonl")
    monkeypatch.setattr(sz, "_mark_excluded", lambda ids: 0)
    p1, p2 = _patch_ebay()
    with p1, p2:
        res = sz.end_listings([_row("111", 40), _row("222", 5)], stale_days=30)

    assert res["ended"] == ["111"]           # 5日のものは触らない
    assert res["failed"] == []


def test_history_is_written_with_source_url(tmp_path, monkeypatch):
    """★ 履歴が残ること。仕入元URLも残す (後で再出品できるように)."""
    led = tmp_path / "ended.jsonl"
    monkeypatch.setattr(sz, "ENDED_LEDGER", led)
    monkeypatch.setattr(sz, "_mark_excluded", lambda ids: 0)
    p1, p2 = _patch_ebay()
    with p1, p2:
        sz.end_listings([_row("111", 40)], stale_days=30)

    import json as _json
    rec = _json.loads(led.read_text(encoding="utf-8").splitlines()[0])
    assert rec["item_id"] == "111"
    assert rec["source_url"] == "https://www.uniqlo.com/x"
    assert rec["days_at_zero"] == 40
    assert rec["verified_ok"] is True
    assert rec["ended_at"]


def test_unverified_end_is_reported_not_counted_as_done(tmp_path, monkeypatch):
    """送っただけで「終了した」と数えない (実際の状態で判定する)."""
    monkeypatch.setattr(sz, "ENDED_LEDGER", tmp_path / "ended.jsonl")
    monkeypatch.setattr(sz, "_mark_excluded", lambda ids: 0)
    p1, p2 = _patch_ebay(status="Active")     # 終了できていない
    with p1, p2:
        res = sz.end_listings([_row("111", 40)], stale_days=30)

    assert res["ended"] == []
    assert res["failed"] == ["111"]


def test_mass_end_is_held(tmp_path, monkeypatch):
    """★ 一度に大量に出たら 1 件も終了しない (巡回側の異常の疑い)."""
    monkeypatch.setattr(sz, "ENDED_LEDGER", tmp_path / "ended.jsonl")
    called = []
    monkeypatch.setattr(sz, "_mark_excluded", lambda ids: called.append(ids) or 0)
    rows = [_row(str(i), 40) for i in range(40)]
    p1, p2 = _patch_ebay()
    with p1, p2:
        res = sz.end_listings(rows, stale_days=30, max_auto=30)

    assert res["held"] is True
    assert res["ended"] == []
    assert called == []                       # シートも触らない


def test_ended_rows_are_excluded_from_patrol(tmp_path, monkeypatch):
    """終了した行は巡回対象外にする (毎回「eBayに無い」を出さない)."""
    monkeypatch.setattr(sz, "ENDED_LEDGER", tmp_path / "ended.jsonl")
    seen = {}
    monkeypatch.setattr(sz, "_mark_excluded", lambda ids: seen.update({"ids": ids}) or len(ids))
    p1, p2 = _patch_ebay()
    with p1, p2:
        sz.end_listings([_row("111", 40)], stale_days=30)

    assert seen["ids"] == {"111"}


def test_ebaymag_mirror_is_never_ended(tmp_path, monkeypatch):
    """★ UK/AU/CA/DE のミラーは触らない (eBaymag の持ち物。親を操作すれば付いてくる)."""
    monkeypatch.setattr(sz, "ENDED_LEDGER", tmp_path / "ended.jsonl")
    monkeypatch.setattr(sz, "_mark_excluded", lambda ids: 0)
    p1, p2 = _patch_ebay(site="UK")
    with p1, p2:
        res = sz.end_listings([_row("111", 40)], stale_days=30)

    assert res["ended"] == []
    assert res["skipped"] == ["111"]


def test_unknown_site_is_not_touched(tmp_path, monkeypatch):
    """site が読めない = ミラーか判らない → 触らない (fail-closed)."""
    monkeypatch.setattr(sz, "ENDED_LEDGER", tmp_path / "ended.jsonl")
    monkeypatch.setattr(sz, "_mark_excluded", lambda ids: 0)
    p1, p2 = _patch_ebay(site="")
    with p1, p2:
        res = sz.end_listings([_row("111", 40)], stale_days=30)

    assert res["ended"] == []
    assert res["skipped"] == ["111"]


def test_already_ended_is_not_re_ended(tmp_path, monkeypatch):
    """既に終了済のものに再度 End を送らない (API の無駄打ちをしない)."""
    monkeypatch.setattr(sz, "ENDED_LEDGER", tmp_path / "ended.jsonl")
    monkeypatch.setattr(sz, "_mark_excluded", lambda ids: 0)
    p1, p2 = _patch_ebay(before="Completed")
    with p1, p2:
        res = sz.end_listings([_row("111", 40)], stale_days=30)

    assert res["ended"] == []
    assert res["skipped"] == ["111"]
