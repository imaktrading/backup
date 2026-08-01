# -*- coding: utf-8 -*-
"""秘書くん (today_brief) の判定ロジック 回帰テスト (2026-08-01)。

I/O (eBay API / スプシ / pdca.db) は collector 側に隔離してあり、ここでは
**「どれを今日やるべきと判断するか」**の純関数だけを固定する。

初版で実際に出た誤りを test 化している:
  - 月初に「1日分未満の遅れ」で毎朝ノイズが1件増えた
  - 未処理依頼の判定を独自実装して決着済みの古い依頼まで拾い 148件 の偽の山を作った
    (→ worktree_board の SSOT 再利用に変更。ここでは閾値/並びのみ検証)
"""
import datetime
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

import today_brief as tb


# ----- month_pace -----

def test_month_pace_on_track():
    p = tb.month_pace(50_000, datetime.date(2026, 8, 15), 100_000)
    assert p["days_in_month"] == 31 and p["elapsed"] == 15
    assert p["expected"] == 100_000 * 15 / 31
    assert p["on_track"] is True          # 実績 5万 > 想定 4.8万
    assert p["remaining_days"] == 16


def test_month_pace_behind():
    p = tb.month_pace(10_000, datetime.date(2026, 8, 20), 100_000)
    assert p["on_track"] is False
    assert p["gap"] > 0
    assert round(p["need_per_day"]) == round(90_000 / 11)


def test_month_pace_last_day_does_not_divide_by_zero():
    p = tb.month_pace(0, datetime.date(2026, 8, 31), 100_000)
    assert p["remaining_days"] == 0 and p["need_per_day"] == 0.0


# ----- days_left -----

def test_days_left():
    t = datetime.date(2026, 8, 1)
    assert tb.days_left("2026-08-06", t) == 5
    assert tb.days_left("2026-07-30", t) == -2      # 期限切れは負
    assert tb.days_left("", t) is None
    assert tb.days_left("not-a-date", t) is None


# ----- 並び順 -----

def test_rank_puts_deadline_work_first():
    items = [
        tb.make_item("P2", "溜まり", "", "", "", count=100),
        tb.make_item("P1", "提案", "", "", "", count=5),
        tb.make_item("P0", "発送(期限5日)", "", "", "", days_left_=5),
        tb.make_item("P0", "発送(期限1日)", "", "", "", days_left_=1),
    ]
    got = [i["title"] for i in tb.rank(items, 4)]
    assert got == ["発送(期限1日)", "発送(期限5日)", "提案", "溜まり"]


def test_rank_limits_output():
    items = [tb.make_item("P2", f"x{i}", "", "", "") for i in range(20)]
    assert len(tb.rank(items, 5)) == 5


def test_same_priority_more_items_first():
    items = [tb.make_item("P2", "少", "", "", "", count=3),
             tb.make_item("P2", "多", "", "", "", count=90)]
    assert [i["title"] for i in tb.rank(items, 2)] == ["多", "少"]


# ----- カテゴリ偏り -----

def test_category_skew_detects_dominant_category():
    import collections
    top, ratio, thin = tb.category_skew(collections.Counter(
        {"TCG": 254, "Tシャツ": 44, "バッグ": 38, "一番くじ": 30, "グリグラ": 4}))
    assert top == "TCG"
    assert round(ratio, 3) == round(254 / 370, 3)     # = 0.686
    assert "グリグラ" in thin                # 全体の1割未満 = 手薄


def test_category_skew_empty_is_safe():
    import collections
    assert tb.category_skew(collections.Counter()) == (None, 0.0, [])


# ----- build_items の閾値 -----

def _sheet(live=380, cats=None, hoju=None, meta=None):
    import collections
    return {"live": live, "by_category": collections.Counter(cats or {"TCG": 100}),
            "listed_recent": {}, "hoju": hoju, "sold_ids": set(), "live_meta": meta or {}}


def _blockers():
    return {"requests": [], "pdca_pending": None, "pdca_oldest_days": None, "tasks": []}


def test_no_bare_pace_fact_item():
    """『売上ペース遅れ ¥N』のような **事実だけの項目は出さない**。

    2026-08-01 ユーザー指摘「事実の羅列で、何をすればいいかが無い」。
    ペースは診断ヘッダで示し、指示側は必ず「何を何件やるか」にする。
    """
    today = datetime.date(2026, 8, 20)
    pace = tb.month_pace(10_000, today, 100_000)
    items = tb.build_items(today, [], 10_000, [], _sheet(), _blockers(), pace)
    assert not [i for i in items if "ペース" in i["title"]]


def test_every_item_is_an_instruction_with_how_and_minutes():
    """全項目が『やり方』と『所要時間』を持つ = 読んだ人が次の動作に移れる。"""
    today = datetime.date(2026, 8, 1)
    orders = [{"date": "2026-07-27", "title": "PSA 10", "amount": "USD 70.00",
               "jpy": 11000, "ship_by": "2026-08-06"}]
    s = _sheet(hoju={"b0": 74, "b1_4": 154, "full": 26, "live_psa": 254})
    b = _blockers()
    b["pdca_pending"] = 14
    items = tb.build_items(today, orders, 0, [], s, b, None)
    assert items
    for it in items:
        assert it["how"], it["title"]
        assert it["minutes"], it["title"]
        assert it["effect"], it["title"]


def test_daily_quota_is_capped_not_all_at_once():
    """『74件やれ』ではなく『今日10件』に切る (毎日削れる量にする)。"""
    today = datetime.date(2026, 8, 1)
    s = _sheet(hoju={"b0": 74, "b1_4": 154, "full": 26, "live_psa": 254})
    it = [i for i in tb.build_items(today, [], 0, [], s, _blockers(), None)
          if "仕入元URL" in i["title"]][0]
    assert f"今日 {tb.DAILY_HOJU_CHECK}件" in it["title"]
    assert it["count"] == 74                      # 母数は残す
    assert it["minutes"] == tb.DAILY_HOJU_CHECK * tb.MIN_PER_HOJU


def test_quota_never_exceeds_remaining_work():
    """残 3件しか無いのに『今日10件』とは言わない。"""
    today = datetime.date(2026, 8, 1)
    s = _sheet(hoju={"b0": 22, "b1_4": 0, "full": 0, "live_psa": 22})
    it = [i for i in tb.build_items(today, [], 0, [], s, _blockers(), None)
          if "仕入元URL" in i["title"]][0]
    assert "今日 10件" in it["title"]              # 22 > 10 なので 10件
    s2 = _sheet(hoju={"b0": 20, "b1_4": 0, "full": 0, "live_psa": 20})
    it2 = [i for i in tb.build_items(today, [], 0, [], s2, _blockers(), None)
           if "仕入元URL" in i["title"]][0]
    assert it2["count"] == 20


# ----- sales_econ: 目標を「件数」に翻訳する -----

def test_sales_econ_translates_target_into_sales_count():
    rows = [("2026-05", 15_000), ("2026-05", 10_000), ("2026-06", 20_000)]
    e = tb.sales_econ(rows, 100_000)
    assert e["n"] == 3
    assert e["avg"] == 15_000
    assert round(e["need_sales"], 2) == round(100_000 / 15_000, 2)


def test_sales_econ_marks_months_that_hit_target():
    rows = [("2026-05", 120_000), ("2026-06", 40_000)]
    e = tb.sales_econ(rows, 100_000)
    assert e["months_ok"] == ["2026-05"] and e["months_ng"] == ["2026-06"]


def test_sales_econ_none_when_no_history():
    assert tb.sales_econ([], 100_000) is None


# ----- トラフィック上限の扱い -----

def test_stale_view_cutoff_is_lowest_returned_value():
    """API は 200件しか返さない (offset 無効・実測)。『閲覧0』と断定せず『以下』と言う。"""
    rows = [("a", 100, 50, 0), ("b", 80, 5, 0)]
    assert tb.stale_view_cutoff(rows) == 5
    assert tb.stale_view_cutoff([]) is None


def test_unshipped_order_is_p0_with_days_left():
    today = datetime.date(2026, 8, 1)
    orders = [{"date": "2026-07-27", "title": "PSA 10 Pokemon", "amount": "USD 70.00",
               "jpy": 11000, "ship_by": "2026-08-06"}]
    items = tb.build_items(today, orders, 0, [], _sheet(), _blockers(), None)
    it = items[0]
    assert it["pri"] == "P0" and it["days_left"] == 5 and "発送" in it["title"]


def test_hot_listing_uses_japanese_title_not_cert_number():
    """PSA 行は `Title` 列が cert 番号なので、和文 `タイトル` を出す。"""
    today = datetime.date(2026, 8, 1)
    meta = {"358730974190": ("PSA10 ゲンガー 033/095 U ポケモンカード", "TCG")}
    rows = [("358730974190", 2835, 130, 0)]
    items = tb.build_items(today, [], 0, rows, _sheet(meta=meta), _blockers(), None)
    hot = [i for i in items if "売れていない" in i["title"]][0]
    assert "ゲンガー" in hot["why"] and "138056961" not in hot["why"]


def test_sold_listing_is_not_proposed_as_unsold():
    today = datetime.date(2026, 8, 1)
    s = _sheet()
    s["sold_ids"] = {"111"}
    items = tb.build_items(today, [], 0, [("111", 999, 500, 0)], s, _blockers(), None)
    assert not [i for i in items if "売れていない" in i["title"]]


def test_hoju_threshold_not_reported_when_small():
    today = datetime.date(2026, 8, 1)
    small = _sheet(hoju={"b0": 3, "b1_4": 5, "full": 1, "live_psa": 9})
    assert not [i for i in tb.build_items(today, [], 0, [], small, _blockers(), None)
                if "仕入元URL" in i["title"]]
    big = _sheet(hoju={"b0": 74, "b1_4": 154, "full": 26, "live_psa": 254})
    assert [i for i in tb.build_items(today, [], 0, [], big, _blockers(), None)
            if "仕入元URL" in i["title"]]


# ----- ボトルネック -----

def test_bottleneck_picks_largest_time_sink():
    s = _sheet(hoju={"b0": 74, "b1_4": 154, "full": 26, "live_psa": 254})
    b = _blockers(); b["pdca_pending"] = 14
    got = tb.bottleneck_note(s, b)
    assert got["name"] == "補URL 補強 (1-4本)"          # 154件×0.5分 = 77分 が最大
    assert got["minutes"] == 77


def test_bottleneck_none_when_nothing_piled_up():
    assert tb.bottleneck_note(_sheet(hoju={}), _blockers()) is None


# ----- 出力 -----

def test_render_marks_unavailable_sources_explicitly():
    """取得できなかった source は『0件』ではなく『不明』と出す (fail-OPEN 防止)。"""
    today = datetime.date(2026, 8, 1)
    txt = tb.render(today, [], None, _sheet(), 0, None, ["eBay 注文 取得不可: HTTPError"], 5)
    assert "取得できなかった source" in txt and "eBay 注文 取得不可" in txt


def test_render_says_nothing_to_do_when_empty():
    today = datetime.date(2026, 8, 1)
    txt = tb.render(today, [], None, _sheet(), 100, None, [], 5)
    assert "出品を回してください" in txt
