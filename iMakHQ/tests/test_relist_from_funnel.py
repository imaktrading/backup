# -*- coding: utf-8 -*-
"""取下再出品 ①取下げ (relist_from_funnel) の選定・保留リスト出力テスト。"""
import csv
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "tools")))
import relist_from_funnel as rf  # noqa: E402


def _row(item_id, price, flags="RELIST", supply_url="https://jp.mercari.com/item/m11111111111",
         category="Wristwatches", title="T"):
    return {"item_id": item_id, "price": str(price), "flags": flags,
            "supply_url": supply_url, "category": category, "title": title}


def test_sku_from_url_mercari_item():
    assert rf.sku_from_url("https://jp.mercari.com/item/m12345678901") == "m12345678901"
    assert rf.sku_from_url("https://jp.mercari.com/item/m12345678901/") == "m12345678901"
    assert rf.sku_from_url("https://jp.mercari.com/item/m12345678901?ref=x") == "m12345678901"
    assert rf.sku_from_url("") == ""


def test_sku_from_url_amazon_asin():
    # listing script (gshock_to_csv) は Amazon /dp/ を ASIN で CustomLabel 化
    assert rf.sku_from_url("https://www.amazon.co.jp/dp/B0DDS4Z29W/?coliid=I29&psc=1") == "B0DDS4Z29W"
    assert rf.sku_from_url("https://www.amazon.co.jp/dp/B0BQHM2SB7") == "B0BQHM2SB7"


def test_sku_from_url_mercari_shops_fallback_tail12():
    # shops/product は /item/m に該当せず末尾12 fallback
    assert rf.sku_from_url("https://jp.mercari.com/shops/product/2JNysv3RcsZP37Dt8Zoaof") == "ZP37Dt8Zoaof"


def test_select_caps_to_10_by_price_desc():
    rows = [_row(f"i{i}", price=i, supply_url=f"https://jp.mercari.com/item/m{i:011d}")
            for i in range(20)]
    picked, total, skipped, already = rf.select(rows, cap=10)
    assert total == 20
    assert skipped == 0
    assert already == 0
    assert len(picked) == 10
    # 価格降順 (19,18,...,10)
    assert [r["item_id"] for r in picked] == [f"i{i}" for i in range(19, 9, -1)]


def test_select_excludes_missing_supply_url():
    rows = [
        _row("a", 100, supply_url="https://jp.mercari.com/item/m99999999999"),
        _row("b", 90, supply_url=""),          # 除外
        _row("c", 80, supply_url="   "),       # 空白のみ → 除外
    ]
    picked, total, skipped, already = rf.select(rows, cap=10)
    assert total == 3
    assert skipped == 2
    assert [r["item_id"] for r in picked] == ["a"]


def test_select_only_relist_flag():
    rows = [
        _row("a", 100, flags="RELIST|NO_SEARCH"),
        _row("b", 90, flags="NO_CONVERT"),     # RELIST でない → 除外
        _row("c", 80, flags=""),
    ]
    picked, total, skipped, already = rf.select(rows, cap=10)
    assert total == 1
    assert [r["item_id"] for r in picked] == ["a"]


def test_select_excludes_already_relisted_by_b_diff():
    # funnel再分析せず「次の10件」を出す核: B列がfunnel itemIDのまま=未着手のみ対象
    rows = [
        _row("done1", 100, supply_url="https://x/u1"),   # B列が新itemIDに変化済=再出品済
        _row("todo1", 90, supply_url="https://x/u2"),    # B列=funnel itemID のまま=未着手
        _row("gone", 80, supply_url="https://x/u3"),     # B列空=除外
        _row("nomatch", 70, supply_url="https://x/u4"),  # sheetに無い=除外
    ]
    b_map = {
        "https://x/u1": "999NEW999",   # ≠ funnel item_id 'done1' → 再出品済
        "https://x/u2": "todo1",        # == funnel item_id → 未着手
        "https://x/u3": "",             # 空 → 除外
        # u4 は b_map に無い
    }
    picked, total, skipped_no_supply, already = rf.select(rows, sheet_b_map=b_map, cap=10)
    assert total == 4
    assert skipped_no_supply == 0
    assert already == 3                              # done1 / gone / nomatch
    assert [r["item_id"] for r in picked] == ["todo1"]


def test_split_by_history_first_vs_second():
    # 一度relistした(=skumap履歴に有る) supply_url は2回目→END停止、無いものは初回→relist
    picked = [
        _row("a", 100, supply_url="https://x/first"),    # 履歴に無い → 初回
        _row("b", 90, supply_url="https://x/again"),     # 履歴に有る → 2回目=END
    ]
    history = {"https://x/again"}
    relist_picks, end_only = rf.split_by_history(picked, history)
    assert [r["item_id"] for r in relist_picks] == ["a"]
    assert [r["item_id"] for r in end_only] == ["b"]


def test_split_by_history_empty_history_all_first():
    picked = [_row("a", 100, supply_url="https://x/u1"), _row("b", 90, supply_url="https://x/u2")]
    relist_picks, end_only = rf.split_by_history(picked, set())
    assert len(relist_picks) == 2 and end_only == []


def test_write_pending_columns_and_sku(tmp_path):
    rows = [_row("itm1", 100, supply_url="https://jp.mercari.com/item/m22222222222",
                 category="Reels", title="Daiwa Reel")]
    picked, _, _, _ = rf.select(rows, cap=10)
    out = tmp_path / "pending.csv"
    rf.write_pending(picked, str(out))
    got = list(csv.DictReader(open(out, encoding="utf-8-sig")))
    assert list(got[0].keys()) == ["sku", "old_item_id", "category", "supply_url", "price", "title"]
    assert got[0]["sku"] == "m22222222222"
    assert got[0]["old_item_id"] == "itm1"
    assert got[0]["category"] == "Reels"
    assert got[0]["supply_url"] == "https://jp.mercari.com/item/m22222222222"
