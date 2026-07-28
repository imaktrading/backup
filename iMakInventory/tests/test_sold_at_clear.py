"""AO(売切日時) を在庫復活時に clear する (2026-07-29 HQ 指摘 39 行).

AO は「その行が今 売切である日時」の意味。旧実装は newly_sold で打つだけで、
在庫復活 (D ○→空) 時に消していなかったため、在庫あり行に売切日時が残っていた
(Days to Sell 集計・CULL/RESTOCK 判断・人の目視を誤らせる)。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

pytestmark = pytest.mark.offline


class FakeWS:
    """batch_update / col_values だけ持つ最小 worksheet."""

    def __init__(self, cols: dict):
        self.cols = cols                      # {col_index: [header, v1, v2, ...]}
        self.batches = []

    def col_values(self, idx):
        return list(self.cols.get(idx, []))

    def batch_update(self, updates, value_input_option=None):
        self.batches.append(updates)


# ---------------------------------------------------------------- 書込側
def _apply(updates):
    import sheet_updater as su
    ws = FakeWS({})
    calls = {}

    def fake_batch(cell_updates, value_input_option=None):
        calls["cells"] = cell_updates

    ws.batch_update = fake_batch
    return su.update_listings_sold_marks(ws, updates), calls


def test_newly_sold_writes_ao_and_restore_clears_it():
    import sheet_updater as su
    res, calls = _apply([
        {"row_index": 10, "is_sold": True, "checked_at": "2026/07/29 06:00:00",
         "sold_at": "2026/07/29 06:00:00"},
        {"row_index": 11, "is_sold": False, "checked_at": "2026/07/29 06:00:00",
         "clear_sold_at": True},
    ])
    ao = su._col_letter(su.LISTINGS_COL_SOLD_AT)
    cells = {c["range"]: c["values"][0][0] for c in calls["cells"]}
    assert cells[f"{ao}10"] == "2026/07/29 06:00:00"     # 売切 → 打つ
    assert cells[f"{ao}11"] == ""                        # 復活 → 消す
    assert res["sold_at_writes"] == 1 and res["sold_at_clears"] == 1


def test_unrelated_rows_do_not_touch_ao():
    """キー無し = AO 非対応 caller → AO を一切触らない (後方互換)"""
    import sheet_updater as su
    res, calls = _apply([{"row_index": 12, "is_sold": False, "checked_at": "t"}])
    ao = su._col_letter(su.LISTINGS_COL_SOLD_AT)
    assert not any(c["range"].startswith(ao) for c in calls["cells"])
    assert res["sold_at_clears"] == 0


def test_monitor_sets_clear_flag_on_restore():
    """monitor_listings の分岐: newly_sold→打刻 / newly_in_stock→clear"""
    import monitor_listings as ml
    import inspect
    src = inspect.getsource(ml.process_sheet)
    assert 'if r.get("delta") == "newly_sold":' in src and '"sold_at"] = checked_at_now' in src
    assert 'elif r.get("delta") == "newly_in_stock":' in src and '"clear_sold_at"] = True' in src


# ---------------------------------------------------------------- 是正ツール
def test_finds_only_in_stock_rows_with_ao():
    import sheet_updater as su
    from tools.clear_stale_sold_at import find_stale_rows
    ws = FakeWS({
        su.LISTINGS_COL_SOLD:    ["売り切れ", "",  "○", "",  ""],
        su.LISTINGS_COL_SOLD_AT: ["売切日時", "2026/07/26 16:14:40", "2026/07/20 1:00:00", "", "x"],
        su.LISTINGS_COL_ITEM_ID: ["itemID", "356917481873", "2", "3", ""],
    })
    rows = find_stale_rows(ws)
    assert [r["row_index"] for r in rows] == [2, 5]      # D=○ の行と AO 空の行は対象外
    assert rows[0]["sold_at"] == "2026/07/26 16:14:40"


def test_compare_and_clear_protects_changed_rows():
    """re-read で値が変わっていた / その後売切になった行は触らない (fail-closed)"""
    import sheet_updater as su
    from tools.clear_stale_sold_at import clear_rows
    ws = FakeWS({
        su.LISTINGS_COL_SOLD:    ["D", "", "○"],
        su.LISTINGS_COL_SOLD_AT: ["AO", "2026/07/26 16:14:40", "2026/07/28 9:00:00"],
    })
    rows = [{"row_index": 2, "sold_at": "2026/07/26 16:14:40", "item_id": "a"},
            {"row_index": 3, "sold_at": "2026/07/28 9:00:00", "item_id": "b"},   # 今は D=○ → 保護
            {"row_index": 2, "sold_at": "違う値", "item_id": "c"}]               # 値不一致 → 保護
    res = clear_rows(ws, rows, "HIGH", execute=False)
    assert res["candidates"] == 1
    assert [m["row_index"] for m in res["mismatch"]] == [3, 2]
    assert ws.batches == []                              # dry-run では書かない


def test_execute_writes_and_archives(tmp_path, monkeypatch):
    import sheet_updater as su
    import tools.clear_stale_sold_at as t
    monkeypatch.setattr(t, "ARCHIVE", str(tmp_path / "arch.jsonl"))
    ws = FakeWS({su.LISTINGS_COL_SOLD: ["D", ""], su.LISTINGS_COL_SOLD_AT: ["AO", "2026/07/26 16:14:40"]})
    res = t.clear_rows(ws, [{"row_index": 2, "sold_at": "2026/07/26 16:14:40", "item_id": "x"}],
                       "LOW", execute=True)
    assert res["cleared"] == 1
    assert ws.batches[0][0]["values"] == [[""]]
    arch = (tmp_path / "arch.jsonl").read_text(encoding="utf-8")
    assert "2026/07/26 16:14:40" in arch and '"row_index": 2' in arch   # 復元可能
