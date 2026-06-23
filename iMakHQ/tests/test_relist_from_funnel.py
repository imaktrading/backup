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
    picked, total, skipped, already, oos, unsup = rf.select(rows, cap=10)
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
    picked, total, skipped, already, oos, unsup = rf.select(rows, cap=10)
    assert total == 3
    assert skipped == 2
    assert [r["item_id"] for r in picked] == ["a"]


def test_select_only_relist_flag():
    rows = [
        _row("a", 100, flags="RELIST|NO_SEARCH"),
        _row("b", 90, flags="NO_CONVERT"),     # RELIST でない → 除外
        _row("c", 80, flags=""),
    ]
    picked, total, skipped, already, oos, unsup = rf.select(rows, cap=10)
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
    picked, total, skipped_no_supply, already, oos, unsup = rf.select(rows, sheet_b_map=b_map, cap=10)
    assert total == 4
    assert skipped_no_supply == 0
    assert already == 3                              # done1 / gone / nomatch
    assert [r["item_id"] for r in picked] == ["todo1"]


def test_select_matches_amazon_asin_across_coliid():
    """回帰: funnel supply_url と スプシA列 の coliid が違っても ASIN で未着手判定が効く。

    旧フルURL照合では coliid 揺れで b_map がヒットせず「未着手」を取りこぼし(=不明扱い)、
    再出品が回らなかった (2026-06-23 ASINキー化の核)。
    """
    rows = [_row("oldid1", 100,
                 supply_url="https://www.amazon.co.jp/dp/B0DDS4Z29W/?coliid=AAA&psc=1")]
    # b_map は ASIN キー (load_current_b_map の戻り)。A列は別 coliid 由来でも同 ASIN。
    b_map = {rf.sku_from_url("https://www.amazon.co.jp/dp/B0DDS4Z29W/?coliid=BBB"): "oldid1"}
    picked, total, skipped_no_supply, already, oos, unsup = rf.select(rows, sheet_b_map=b_map, cap=10)
    assert already == 0
    assert [r["item_id"] for r in picked] == ["oldid1"]   # coliid 差を ASIN が吸収=未着手で拾える


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


# ---- Phase② 在庫ゲート (監視くん『売り切れ』に従う・fail-closed) ----
import datetime as _dt  # noqa: E402


def test_parse_check_time_variants():
    assert rf.parse_check_time("2026/6/2 10:44:39") == _dt.datetime(2026, 6, 2, 10, 44, 39)
    assert rf.parse_check_time("2026/06/23 16:08:15") == _dt.datetime(2026, 6, 23, 16, 8, 15)
    assert rf.parse_check_time("2026/6/23") == _dt.datetime(2026, 6, 23, 0, 0, 0)  # 時刻欠落OK
    assert rf.parse_check_time("") is None
    assert rf.parse_check_time("ゴミ") is None


def test_stock_verdict_fail_closed():
    now = _dt.datetime(2026, 6, 23, 12, 0, 0)
    fresh = _dt.datetime(2026, 6, 23, 6, 0, 0)   # 6h前
    old = _dt.datetime(2026, 6, 20, 6, 0, 0)     # 3日前
    assert rf.stock_verdict({"sold_out": False, "check_time": fresh}, now) == "OK"
    assert rf.stock_verdict({"sold_out": True, "check_time": fresh}, now) == "SOLD_OUT"
    assert rf.stock_verdict({"sold_out": False, "check_time": old}, now) == "STALE"
    assert rf.stock_verdict({"sold_out": False, "check_time": None}, now) == "STALE"
    assert rf.stock_verdict(None, now) == "NO_ROW"   # スプシ行無し → 出さない


def test_select_stock_gate_excludes_sold_out_and_stale():
    """在庫ゲート: 未着手でも 売り切れ○/古い/行無し は再出品しない (B0B78CZ3W3 事故対策)。"""
    now = _dt.datetime(2026, 6, 23, 12, 0, 0)
    fresh = _dt.datetime(2026, 6, 23, 6, 0, 0)
    old = _dt.datetime(2026, 6, 1, 6, 0, 0)
    rows = [
        _row("ok", 100, supply_url="https://www.amazon.co.jp/dp/B000000001"),   # 在庫あり→出す
        _row("so", 90, supply_url="https://www.amazon.co.jp/dp/B000000002"),    # 売り切れ→除外
        _row("st", 80, supply_url="https://www.amazon.co.jp/dp/B000000003"),    # 古い→除外
        _row("nr", 70, supply_url="https://www.amazon.co.jp/dp/B000000004"),    # 行無し→除外
    ]
    b_map = {f"B00000000{i}": iid for i, iid in [(1, "ok"), (2, "so"), (3, "st"), (4, "nr")]}
    # nr は stock_index に無い (行無し)
    stock = {
        "B000000001": {"b": "ok", "sold_out": False, "check_time": fresh},
        "B000000002": {"b": "so", "sold_out": True, "check_time": fresh},
        "B000000003": {"b": "st", "sold_out": False, "check_time": old},
    }
    picked, total, no_supply, already, oos, unsup = rf.select(
        rows, sheet_b_map=b_map, stock_index=stock, now=now, cap=10)
    assert [r["item_id"] for r in picked] == ["ok"]   # 在庫ありのみ
    assert already == 0                                # 全て未着手 (B==funnel)
    assert oos == 3                                    # so/st/nr = 仕入不可で除外


def test_select_no_stock_index_keeps_old_behavior():
    # stock_index 未指定 (None) なら在庫ゲートは効かない (従来挙動・後方互換)
    rows = [_row("a", 100, supply_url="https://www.amazon.co.jp/dp/B000000001")]
    b_map = {"B000000001": "a"}
    picked, total, no_supply, already, oos, unsup = rf.select(rows, sheet_b_map=b_map, cap=10)
    assert [r["item_id"] for r in picked] == ["a"] and oos == 0


def test_relist_candidates_excludes_psa_ccg():
    """PSA(CCG)は独立パイプライン管轄 → 取下げ再出品の候補から完全除外 (2026-06-23 指示)。"""
    rows = [
        _row("w", 100, category="Wristwatches"),
        _row("psa", 90, category="CCG Individual Cards", supply_url="https://jp.mercari.com/item/m44444444444"),
    ]
    cands = rf.relist_candidates(rows)
    assert [r["item_id"] for r in cands] == ["w"]   # PSA は候補にすら入らない


def test_select_category_gate_excludes_unsupported():
    """カテゴリゲート: ②が再出品できないカテゴリは取り下げない (取下げ→再出品漏れ防止)。

    2026-06-23 事故対策。例は Action Figures (②未対応だが独立除外はされないカテゴリ)。
    PSA(CCG)は relist_candidates 段で完全除外なのでここの例には使わない。
    """
    rows = [
        _row("w", 100, supply_url="https://www.amazon.co.jp/dp/B000000001", category="Wristwatches"),
        _row("r", 90, supply_url="https://www.amazon.co.jp/dp/B000000002", category="Reels"),
        _row("fig", 95, supply_url="https://jp.mercari.com/item/m33333333333", category="Action Figures"),
    ]
    picked, total, no_supply, already, oos, unsup = rf.select(
        rows, cap=10, supported_categories={"Wristwatches", "Reels"})
    assert unsup == 1                                       # Action Figures = ②未対応で除外
    assert {r["item_id"] for r in picked} == {"w", "r"}     # fig は取り下げない


def test_select_no_category_gate_keeps_all():
    # supported_categories 未指定なら従来どおり全カテゴリ対象 (後方互換)。CCG以外で確認。
    rows = [_row("fig", 95, supply_url="https://jp.mercari.com/item/m33333333333",
                 category="Action Figures")]
    picked, total, no_supply, already, oos, unsup = rf.select(rows, cap=10)
    assert unsup == 0 and [r["item_id"] for r in picked] == ["fig"]


def test_write_pending_columns_and_sku(tmp_path):
    rows = [_row("itm1", 100, supply_url="https://jp.mercari.com/item/m22222222222",
                 category="Reels", title="Daiwa Reel")]
    picked, _, _, _, _, _ = rf.select(rows, cap=10)
    out = tmp_path / "pending.csv"
    rf.write_pending(picked, str(out))
    got = list(csv.DictReader(open(out, encoding="utf-8-sig")))
    assert list(got[0].keys()) == ["sku", "old_item_id", "category", "supply_url", "price", "title"]
    assert got[0]["sku"] == "m22222222222"
    assert got[0]["old_item_id"] == "itm1"
    assert got[0]["category"] == "Reels"
    assert got[0]["supply_url"] == "https://jp.mercari.com/item/m22222222222"
