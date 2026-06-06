# -*- coding: utf-8 -*-
"""取下再出品 進捗ダッシュボード (relist_dashboard.build_rows) の状態判定・並び。"""
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "tools")))
import relist_dashboard as rd  # noqa: E402


def _row(item_id, price, supply_url, flags="RELIST", category="Wristwatches", title="T"):
    return {"item_id": item_id, "price": str(price), "supply_url": supply_url,
            "flags": flags, "category": category, "title": title}


def test_build_rows_state_and_order():
    funnel = [
        _row("done1", 100, "https://x/u1"),    # B変化=済
        _row("todo1", 90, "https://x/u2"),     # B==funnel=未
        _row("unk1", 80, "https://x/u3"),      # B空=不明
        _row("nope", 70, "", flags="NO_CONVERT"),  # RELISTでない=対象外
    ]
    b_map = {"https://x/u1": "999NEW", "https://x/u2": "todo1", "https://x/u3": ""}
    rows, summary = rd.build_rows(funnel, b_map)
    assert summary == {"total": 3, "done": 1, "todo": 1, "unknown": 1}
    # 価格降順 (100,90,80) かつ # は1始まり
    assert [r[0] for r in rows] == [1, 2, 3]
    assert [r[5] for r in rows] == ["done1", "todo1", "unk1"]   # 旧ItemID列
    states = {r[5]: r[1] for r in rows}
    assert states["done1"] == "✅済" and rows[0][6] == "999NEW"  # 新ItemID列
    assert states["todo1"] == "⏳未" and rows[1][6] == ""
    assert states["unk1"] == "❓不明"


def test_build_rows_excludes_no_supply_url():
    funnel = [_row("a", 50, ""), _row("b", 40, "https://x/u")]
    b_map = {"https://x/u": "b"}
    rows, summary = rd.build_rows(funnel, b_map)
    assert summary["total"] == 1                # supply_url無は対象外
    assert rows[0][5] == "b"
