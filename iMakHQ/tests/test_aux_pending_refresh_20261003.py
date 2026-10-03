"""補URL の目視待ちの棚卸し (2026-10-03 ユーザー「そんなの夜のうちにやっとかないと」)。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
import aux_pending_refresh as A  # noqa: E402

ROWS = [{"itemID": "1", "url": "u1", "price": None}, {"itemID": "2", "url": "u2", "price": None},
        {"itemID": "3", "url": "u3", "price": 5000}, {"itemID": "", "url": "u4", "price": None}]


def test_sold_removed_live_gets_price_unknown_untouched():
    res = {"u1": {"live": False, "price": None}, "u2": {"live": True, "price": 12000},
           "u3": {"live": None, "price": None}}
    keep, removed = A.plan(ROWS, res, today="2026-10-04")
    assert [r["url"] for r in removed] == ["u1"]
    k = {r["url"]: r for r in keep}
    assert k["u2"]["price"] == 12000 and k["u2"]["checked"] == "2026-10-04"
    assert k["u3"]["price"] == 5000 and "checked" not in k["u3"]      # 判らない = 触らない
    assert "u4" in k                                                    # 結果なし = 触らない


def test_only_rows_with_item_id_are_checked():
    assert A.urls_to_check(ROWS) == ["u1", "u2", "u3"]
