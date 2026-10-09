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


def test_live_row_keeps_listing_name_20261010():
    """出品名も残す (番号違い・刷り違いの門を効かせるため)。"""
    import aux_pending_refresh as R
    keep, _ = R.plan([{"itemID": "1", "url": "u"}], {"u": {"live": True, "price": 100, "name": "PSA10 ピカチュウ 020/M-P"}},
                     today="2026-10-10")
    assert keep[0]["name"] == "PSA10 ピカチュウ 020/M-P" and keep[0]["price"] == 100
