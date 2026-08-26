# -*- coding: utf-8 -*-
"""出品した分だけ棚を空ける — 落とす出品の選定 (2026-08-26)。

## なぜ
eBay の出品リミットは **金額** ($1M)。件数は 12,000中5,807 でスカスカで、詰まっているのは金額だけ。
出品を続ける限り棚は埋まるので、出した分より少し多く落とさないと出品が止まる。

## 決めたこと (ユーザー確定)
- **カテゴリを跨いで横並び**で選ぶ。売れないカテゴリの中で最適化しても、売れるカテゴリの
  1件には及ばない (棚$1000あたり利益: Tシャツ¥3,501 / TCG¥97 / G-SHOCK¥0)。
- 落とす額は **その日の出品額 × 1.0** (出した分だけ入れ替える。棚は一定)。
- 順は ①仕入元が死んでいる → ②出品30日超・未販売。
  **②に閾値は設けず、アクセス (累計表示) の少ない順**に落とす。
  「表示◯回以上なら」という線はカテゴリごとに桁が違い、必ずどちらかを取りこぼす。
- 空く額は **ミラー込み**。US価格だけで並べると効き目を読み違える
  (実測: ある層は US $63,808 に対し棚は $272,890 空く)。
"""
import os
import sys

_TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import shelf_evict as SE  # noqa: E402


def _row(iid="1", qty=1, sold=0, s90=0, watch=0, impr=5000, price=100.0, age=200, title=None,
         cat="TCG"):
    r = _mk(iid, qty, sold, s90, watch, impr, price, age, title)
    r["_cat"] = cat
    return r


def _cat_of(r):
    return r.get("_cat")


def _mk(iid, qty, sold, s90, watch, impr, price, age, title):
    return {"item_id": iid, "title": title or f"T{iid}", "qty": qty, "sold_qty": sold,
            "sales90": s90, "watch": watch, "impr_total": impr, "price": price, "age_days": age}


def _shelf(r):
    return r["price"]


# ---- 誰を落とす対象にするか ----

def test_out_of_stock_is_first():
    assert SE.tier_of(_row(qty=0), category='TCG') == SE.TIER_OOS


def test_old_and_unsold_is_second():
    assert SE.tier_of(_row(age=200, sold=0), category="TCG") == SE.TIER_STALE
    assert SE.tier_of(_row(age=200, sold=0), category="G-shock") == SE.TIER_STALE


def test_earning_categories_are_left_alone_when_supply_alive():
    """★仕入元が活きているものは TCG / G-SHOCK だけ落とす (2026-08-26 ユーザー確定)。

    Tシャツは棚$1,000あたり利益 ¥3,501 で一番稼いでいる (TCG ¥97 / G-SHOCK ¥0 の36倍)。
    そこを減らすのは目的 (棚あたり売上の最大化) に反する。
    """
    assert SE.tier_of(_row(age=200), category="Tシャツ") is None
    assert SE.tier_of(_row(age=200), category="一番くじ") is None


def test_dead_supply_is_dropped_in_every_category():
    """★仕入元が死んでいる分は全カテゴリ。買えないものを残す意味は無い。"""
    assert SE.tier_of(_row(qty=0), category="Tシャツ") == SE.TIER_OOS
    assert SE.tier_of(_row(qty=0), category=None) == SE.TIER_OOS


def test_new_listing_is_left_alone():
    """出品30日未満はまだ判定できない。"""
    assert SE.tier_of(_row(age=10), category='TCG') is None


def test_sold_is_left_alone():
    assert SE.tier_of(_row(sold=1), category='TCG') is None
    assert SE.tier_of(_row(s90=1), category='TCG') is None


def test_out_of_stock_wins_even_with_demand():
    """在庫切れは買えないので、watcher が居ても売れた実績があっても落とす側。"""
    assert SE.tier_of(_row(qty=0, watch=9, sold=3, age=5), category='TCG') == SE.TIER_OOS


def test_watcher_alone_does_not_protect():
    """★watcher が付いていても、30日超で売れていなければ対象。

    「見られていて watcher が付いていても売れないなら畳む」(ユーザー指摘)。
    """
    assert SE.tier_of(_row(watch=5, sold=0, age=200), category='TCG') == SE.TIER_STALE


# ---- どの順で落とすか ----

def test_second_tier_orders_by_access_ascending():
    """★閾値ではなく順位。アクセスの少ないものから落ちる。"""
    seen_little = _row("little", impr=50, price=100.0)
    seen_a_lot = _row("lots", impr=9000, price=100.0)
    picked, _ = SE.pick([seen_a_lot, seen_little], target=50, shelf_of=_shelf, cat_of=_cat_of)
    assert picked[0][1]["item_id"] == "little"


def test_out_of_stock_beats_everything():
    oos = _row("oos", qty=0, price=10.0)
    stale = _row("stale", impr=0, price=900.0)
    picked, _ = SE.pick([stale, oos], target=5, shelf_of=_shelf, cat_of=_cat_of)
    assert picked[0][1]["item_id"] == "oos"


def test_out_of_stock_orders_by_amount():
    """①は1件で空く額が大きいほうが先 (少ない件数で枠を作れる)。"""
    small = _row("s", qty=0, price=10.0)
    big = _row("b", qty=0, price=900.0)
    picked, _ = SE.pick([small, big], target=5, shelf_of=_shelf, cat_of=_cat_of)
    assert picked[0][1]["item_id"] == "b"


def test_picks_until_target_and_stops():
    rows = [_row(str(i), qty=0, price=100.0) for i in range(10)]
    picked, total = SE.pick(rows, target=250, shelf_of=_shelf, cat_of=_cat_of)
    assert total >= 250 and len(picked) == 3


def test_nothing_to_drop_returns_empty():
    picked, total = SE.pick([_row(age=5)], target=1000, shelf_of=_shelf, cat_of=_cat_of)
    assert picked == [] and total == 0


def test_no_fixed_threshold_in_source():
    """★閾値を復活させない。表示回数の固定値で切ると必ずどちらかを取りこぼす。"""
    src = open(os.path.join(_TOOLS, "shelf_evict.py"), encoding="utf-8").read()
    assert "MIN_SHOWN_FLOOR" not in src
    assert "shown_floor" not in src


def test_ratio_is_one():
    """出した分だけ入れ替える。余計に落とすと、育つ前のものを捨てる。"""
    assert SE.RATIO == 1.0
