"""Regression: 2026-06-18 — RESTOCK スプシ書戻し(状態同期・送信後verify)。

RESTOCK確定→Revise CSV→手動UL の後、実eBay qty を verify してからスプシ更新(fail-OPEN禁止)。
qty>=1=実行済 / qty=0=入稿待ち(silentに済扱いしない) / None=不明(fail-closed: 済にしない)。
"""
import importlib.util
from pathlib import Path

_P = Path(__file__).resolve().parent.parent / "iMakHQ" / "tools" / "psa_restock_writeback.py"
_spec = importlib.util.spec_from_file_location("psa_restock_writeback_t", _P)
import sys
sys.path.insert(0, str(_P.parent))
wb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wb)


def test_classify_by_actual_qty():
    items = [{"itemID": "1"}, {"itemID": "2"}, {"itemID": "3"}, {"itemID": "4"}]
    qty = {"1": 1, "2": 0, "3": None, "4": 5}
    c = wb.classify_restock(items, qty)
    assert c["done"] == ["1", "4"]       # qty>=1 = 実行済
    assert c["pending"] == ["2"]         # qty=0 = 入稿待ち(済にしない)
    assert c["unknown"] == ["3"]         # 取得不能 = 不明(fail-closed)
    assert c["status"]["1"] == wb.ST_DONE
    assert c["status"]["2"] == wb.ST_PENDING
    assert c["status"]["3"] == wb.ST_UNKNOWN


def test_empty_itemid_skipped():
    c = wb.classify_restock([{"itemID": ""}, {"itemID": "x"}], {"x": 1})
    assert c["done"] == ["x"] and "" not in c["status"]


def test_qty_zero_never_marked_done():
    # fail-OPEN防止: qty=0 は絶対 done にしない(未反映を済と書かない)
    c = wb.classify_restock([{"itemID": "a"}], {"a": 0})
    assert c["done"] == [] and c["pending"] == ["a"]
