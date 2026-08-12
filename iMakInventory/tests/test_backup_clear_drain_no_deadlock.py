"""補URL消込の恒久 HOLD (deadlock) 再発防止 regression test.

★ 2026-08-12 制定。実害: 08-09 22:53 に候補 30 件 (>閾値20) で HOLD → 以後 backlog が
減らないまま 30→75 に単調増加し、**15 cycle 連続で同じ ALERT** をデスクトップに吐き続けた
(4日間)。ガードが自分で backlog を育て、自分で永久に発火し続ける自己増殖アラーム。

仕様 (ここを壊したら deadlock 再発):
- 急増ガードの判定基準は **今 cycle 新規** の候補数 (積み残しを含む総数ではない)。
- 閾値内なら 1 cycle あたり CLEAR_DRAIN_CAP 件まで消し、超過は次 cycle 繰越 (deferred)。
  → backlog は cycle 毎に必ず減る = 人手ドレイン不要 = ALERT が鳴りっぱなしにならない。
- ドレインは **初出が古い順** (滞留の固定化防止)。
- scraper 系統崩壊 (新規が一気に湧く) は従来どおり HOLD + ALERT で止める。
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _ws(rows: dict):
    ws = MagicMock()
    ws.batch_get = MagicMock(return_value=[[rows.get(r, ["", "", "", "", ""])]
                                           for r in sorted(rows)])
    ws.batch_update = MagicMock()
    return ws


def _cands(n, start=1):
    return [{"row_index": i, "slot": 0, "expected_url": f"u{i}"}
            for i in range(start, start + n)]


# ============================================================================
# 急増ガードの判定基準 = 新規のみ
# ============================================================================
def test_backlog_over_threshold_does_not_hold_when_new_is_small():
    """積み残しが閾値超でも、新規が少なければ HOLD しない (deadlock 再発防止の中核)."""
    from sheet_updater import clear_sold_backup_cells, CLEAR_SURGE_THRESHOLD
    n = CLEAR_SURGE_THRESHOLD * 3          # 60 件の backlog
    rows = {i: ["u%d" % i, "", "", "", ""] for i in range(1, n + 1)}
    res = clear_sold_backup_cells(_ws(rows), _cands(n), new_count=2, drain_cap=None)
    assert res["held"] is False and res["surge"] is False
    assert res["cleared"] == n


def test_new_surge_still_holds():
    """新規が一気に湧く (= scraper 系統崩壊の疑い) は従来どおり HOLD + 実書込ゼロ."""
    from sheet_updater import clear_sold_backup_cells, CLEAR_SURGE_THRESHOLD
    n = CLEAR_SURGE_THRESHOLD + 1
    ws = _ws({})
    res = clear_sold_backup_cells(ws, _cands(n), new_count=n)
    assert res["held"] is True and res["surge"] is True and res["cleared"] == 0
    assert res["new_count"] == n
    ws.batch_get.assert_not_called()
    ws.batch_update.assert_not_called()


def test_new_count_omitted_falls_back_to_total():
    """new_count 未指定 (手動 tool 等) は全件新規扱い = 安全側 (後方互換)."""
    from sheet_updater import clear_sold_backup_cells, CLEAR_SURGE_THRESHOLD
    res = clear_sold_backup_cells(_ws({}), _cands(CLEAR_SURGE_THRESHOLD + 1))
    assert res["held"] is True


# ============================================================================
# ドレイン上限 (backlog が毎 cycle 必ず減る)
# ============================================================================
def test_drain_cap_clears_partially_and_defers_rest():
    from sheet_updater import clear_sold_backup_cells, CLEAR_DRAIN_CAP
    n = CLEAR_DRAIN_CAP + 7
    rows = {i: ["u%d" % i, "", "", "", ""] for i in range(1, n + 1)}
    res = clear_sold_backup_cells(_ws(rows), _cands(n), new_count=1,
                                  drain_cap=CLEAR_DRAIN_CAP)
    assert res["cleared"] == CLEAR_DRAIN_CAP
    assert res["deferred"] == 7
    assert res["held"] is False        # 繰越は HOLD ではない = ALERT にしない


def test_backlog_drains_to_zero_over_cycles():
    """繰越を含む backlog が cycle を重ねて必ず 0 に収束する (恒久 HOLD しない)."""
    from sheet_updater import clear_sold_backup_cells, CLEAR_DRAIN_CAP
    backlog = _cands(75)               # 08-12 の実測 backlog と同数
    cycles = 0
    while backlog:
        rows = {c["row_index"]: [c["expected_url"], "", "", "", ""] for c in backlog}
        res = clear_sold_backup_cells(_ws(rows), backlog, new_count=0,
                                      drain_cap=CLEAR_DRAIN_CAP)
        assert res["held"] is False
        assert res["cleared"] > 0      # 1 件も進まない cycle があれば deadlock
        backlog = backlog[res["cleared"]:]
        cycles += 1
        assert cycles <= 10            # 75 件は 8h×4 cycle 程度で終わるはず
    assert cycles == 4


# ============================================================================
# 古い順ドレイン + 新規判定 (caller 側)
# ============================================================================
def test_order_puts_oldest_first_and_counts_new():
    from monitor_listings import order_backup_clear_candidates
    seen = {"5:0:old_a": "2026-08-09T00:00:00", "6:0:old_b": "2026-08-10T00:00:00"}
    cands = [{"row_index": 9, "slot": 0, "expected_url": "fresh"},
             {"row_index": 6, "slot": 0, "expected_url": "old_b"},
             {"row_index": 5, "slot": 0, "expected_url": "old_a"}]
    ordered, new_count, updated = order_backup_clear_candidates(cands, seen)
    assert [c["expected_url"] for c in ordered] == ["old_a", "old_b", "fresh"]
    assert new_count == 1                       # fresh のみ新規
    assert updated["5:0:old_a"] == "2026-08-09T00:00:00"   # 初出は保持 (毎回更新しない)
    assert set(updated) == {"5:0:old_a", "6:0:old_b", "9:0:fresh"}


def test_seen_state_drops_disappeared_candidates():
    """消えた候補は state から落ちる (肥大化防止)。再出現時は新規扱い = 安全側."""
    from monitor_listings import order_backup_clear_candidates
    seen = {"1:0:gone": "2026-08-01T00:00:00", "2:0:stay": "2026-08-02T00:00:00"}
    cands = [{"row_index": 2, "slot": 0, "expected_url": "stay"}]
    _, new_count, updated = order_backup_clear_candidates(cands, seen)
    assert new_count == 0
    assert updated == {"2:0:stay": "2026-08-02T00:00:00"}


def test_empty_seen_treats_all_as_new_failsafe():
    """state 読み失敗 (空) は全件新規 = ガードが厳しい側に倒れる."""
    from monitor_listings import order_backup_clear_candidates
    cands = _cands(3)
    _, new_count, _ = order_backup_clear_candidates(cands, {})
    assert new_count == 3
