# -*- coding: utf-8 -*-
"""棚: Tシャツ (メルカリ・ラクマ仕入) を30日で回す / 有在庫は落とさない (2026-09-15)。

ユーザー「Tシャツは自動出品がほぼ完了したので、対象外から外してもいいかなと。ただ、有在庫をどうしようかと。
モンベルにも有在庫ある」「GOKUのフィギュアもひとつ有在庫」→ 提案に「そだね。グループ名を対象外 (有在庫)にしておいて」。
実測 (9/14 ファネル・在庫あり US): Tシャツ 公式仕入 64件 (売れ7) / メルカリ仕入 23件 (中央値204日・売れ0) /
ラクマ仕入 12件 (150日・売れ0) / 有在庫 2件。モンベル 有在庫4 / 仕入元不明5 / メルカリ2。
"""
import os
import sys

HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HQ, "tools"))

import listing_funnel as lf  # noqa: E402
import shelf_evict as SE  # noqa: E402

GOKU = "356781455394"   # S.H.Figuarts Son Goku DAIMA (有在庫シートに載っている)


def _row(iid, title, age=60, qty=1, sold=0, supply=""):
    return {"item_id": iid, "title": title, "qty": qty, "sold_qty": sold, "sales90": 0,
            "age_days": age, "impr_total": 0, "price": 50.0, "watch": 0, "supply_url": supply}


def test_category_for():
    assert SE.category_for(GOKU, "フィギュア", "", onhand={GOKU}) == SE.ONHAND
    assert SE.category_for("1", "Tシャツ", "https://jp.mercari.com/item/m1") == "Tシャツ"
    assert SE.category_for("2", "Tシャツ", "https://item.fril.jp/abc") == "Tシャツ"
    assert SE.category_for("3", "Tシャツ", "https://www.uniqlo.com/jp/ja/products/E1") == "Tシャツ(公式等)"
    assert SE.category_for("4", "Tシャツ", "") == "Tシャツ(公式等)"
    assert SE.category_for("5", "TCG", "https://jp.mercari.com/item/m5") == "TCG"


def test_one_off_tshirt_is_dropped_at_30_days_but_onhand_and_official_are_not():
    assert SE.STALE_MAX_AGE["Tシャツ"] == 30
    t = "One Piece Luffy Anime Graphic T-Shirt UNIQLO UT Black US L (JP XL) NWT"
    assert SE.tier_of(_row("1", t, age=31), category=SE.category_for("1", "Tシャツ", "https://jp.mercari.com/item/m1")) == SE.TIER_STALE
    assert SE.tier_of(_row("1", t, age=30), category="Tシャツ") is None
    assert SE.tier_of(_row("3", t, age=400), category=SE.category_for("3", "Tシャツ", "")) is None
    assert SE.tier_of(_row(GOKU, "S.H.Figuarts Son Goku", age=500),
                      category=SE.category_for(GOKU, "フィギュア", "", onhand={GOKU})) is None


def test_onhand_ids_from_sheet_and_empty_supply_rows():
    oh = [["", "", ""], ["", "", ""], ["", "Item number", "Title"], ["", GOKU, "Goku"], ["", "", "blank"]]
    prod = [["A", "B"], ["https://jp.mercari.com/item/m1", "358000000001"], ["", "356959007432"], ["", ""]]
    assert SE.onhand_ids_from(oh, [prod]) == {GOKU, "356959007432"}


def test_funnel_group_names():
    assert lf.evict_group(_row(GOKU, "S.H.Figuarts Son Goku", age=500), onhand={GOKU}) == "対象外 (有在庫)"
    t = "Dragon Ball Goku Anime Graphic T-Shirt UNIQLO UT Orange US S (JP M) NWT"
    assert lf.evict_group(_row("1", t, age=60, supply="https://jp.mercari.com/item/m1"),
                          onhand=set(), sheet_cat="Tシャツ").startswith("落とす")
    assert lf.evict_group(_row("1", t, age=10, supply="https://jp.mercari.com/item/m1"),
                          onhand=set(), sheet_cat="Tシャツ") == lf._EVICT_WAIT
    assert lf.evict_group(_row("3", t, age=60), onhand=set(), sheet_cat="Tシャツ") == lf._EVICT_OUT
    assert lf.evict_group(_row("3", t, age=60)) == lf._EVICT_OUT          # 材料なしの呼び方は今までどおり


def test_panel_tip_matches_the_rule():
    src = open(os.path.join(HQ, "control_panel.py"), encoding="utf-8").read()
    i = src.index('"label": "📉 棚② ')
    tip = src[i:i + 2500]
    assert "有在庫" in tip and "Tシャツ" in tip
    assert "365日" not in tip[:tip.index('},')]
