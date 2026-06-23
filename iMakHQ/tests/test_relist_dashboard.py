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
    assert summary == {"total": 3, "done": 1, "todo": 1, "unknown": 1, "oos": 0}
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


def test_build_rows_matches_asin_across_coliid_not_unknown():
    """回帰: coliid 違いでも ASIN で済/未判定 → 「不明」誤計上しない (2026-06-23)。

    funnel supply_url(coliid=AAA) と スプシA列(coliid=BBB) が同 ASIN。旧フルURL照合では
    b_map がヒットせず ❓不明 に落ちていた。
    """
    import relist_from_funnel as rf
    funnel = [_row("oldid", 100, "https://www.amazon.co.jp/dp/B0DDS4Z29W/?coliid=AAA")]
    b_map = {rf.sku_from_url("https://www.amazon.co.jp/dp/B0DDS4Z29W/?coliid=BBB"): "oldid"}
    rows, summary = rd.build_rows(funnel, b_map)
    assert summary == {"total": 1, "done": 0, "todo": 1, "unknown": 0, "oos": 0}   # 未着手で拾える
    assert rows[0][1] == "⏳未"


def test_build_rows_processing_time_column():
    """アイテム毎の処理日時 (③書戻し完了時刻) を列表示。history(ASIN→日時)から引く (2026-06-23)。"""
    funnel = [
        _row("done1", 100, "https://www.amazon.co.jp/dp/B000000001"),   # 再出品済=処理日時あり
        _row("todo1", 90, "https://www.amazon.co.jp/dp/B000000002"),    # 未着手=処理日時なし
    ]
    b_map = {"B000000001": "999NEW", "B000000002": "todo1"}
    times = {"B000000001": "2026-06-23 16:51:00"}
    rows, summary = rd.build_rows(funnel, b_map, times_map=times)
    by_old = {r[5]: r for r in rows}
    assert by_old["done1"][7] == "2026-06-23 16:51:00"   # 処理日時列
    assert by_old["done1"][8] == "https://www.amazon.co.jp/dp/B000000001"  # URLは最終列
    assert by_old["todo1"][7] == ""                      # 未着手は空


def test_build_rows_marks_sold_out_distinctly():
    """在庫切れ(監視くん『売り切れ』○)は 🔴在庫切れ として区別。未着手に紛れさせない。

    元の「不明3件」の正体 = 監視くん取下げ済(OOS)。stock_index を渡すと正しく可視化される。
    """
    import relist_from_funnel as rf
    funnel = [
        _row("live", 100, "https://www.amazon.co.jp/dp/B000000001"),   # 在庫あり=未
        _row("dead", 90, "https://www.amazon.co.jp/dp/B000000002"),    # 売り切れ=在庫切れ
    ]
    b_map = {"B000000001": "live", "B000000002": "dead"}
    stock = {
        "B000000001": {"b": "live", "sold_out": False, "check_time": None},
        "B000000002": {"b": "dead", "sold_out": True, "check_time": None},
    }
    rows, summary = rd.build_rows(funnel, b_map, stock_index=stock)
    assert summary == {"total": 2, "done": 0, "todo": 1, "unknown": 0, "oos": 1}
    states = {r[5]: r[1] for r in rows}
    assert states["live"] == "⏳未"
    assert states["dead"] == "🔴在庫切れ"
