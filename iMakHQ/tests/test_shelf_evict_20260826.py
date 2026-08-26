# -*- coding: utf-8 -*-
"""出品した分だけ棚を空ける — 落とす出品の選定 (2026-08-26)。

## なぜ
eBay の出品リミットは **金額** ($1M)。件数は 12,000中5,807 でスカスカで、詰まっているのは金額だけ。
出品を続ける限り棚は埋まるので、出した分より少し多く落とさないと出品が止まる。

## 決めたこと (ユーザー確定)
- **カテゴリを跨いで横並び**で選ぶ。売れないカテゴリの中で最適化しても、売れるカテゴリの
  1件には及ばない (棚$1000あたり利益: Tシャツ¥3,501 / TCG¥97 / G-SHOCK¥0)。
- 落とす額は **その日の出品額 × 1.3**。毎日少しずつ空けて、良いカテゴリに回す。
- 同順位内は **ミラー込みで空く額** の大きい順。US価格で並べると効き目を読み違える
  (実測: ②の279件は US $63,808 だが棚は $272,890 空く)。
"""
import os
import sys

_TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import shelf_evict as SE  # noqa: E402


def _row(iid="1", qty=1, sold=0, s90=0, watch=0, impr=5000, price=100.0, title=None):
    return {"item_id": iid, "title": title or f"T{iid}", "qty": qty, "sold_qty": sold,
            "sales90": s90, "watch": watch, "impr_total": impr, "price": price}


# ---- 誰を落とすか ----

def test_out_of_stock_is_first():
    assert SE.tier_of(_row(qty=0), 1000) == SE.TIER_OOS


def test_shown_but_no_watcher_is_second():
    assert SE.tier_of(_row(impr=5000, watch=0), 1000) == SE.TIER_NO_WATCH


def test_one_watcher_is_third():
    assert SE.tier_of(_row(impr=5000, watch=1), 1000) == SE.TIER_THIN


def test_not_shown_enough_is_left_alone():
    """見せ足りないものは落とす相手ではない (露出を作る相手)。

    実測: 90日超 × watcher0 の 196件のうち 51% は表示1000回未満だった。
    日数や watcher だけで切ると、この半分を巻き込む。
    """
    assert SE.tier_of(_row(impr=200, watch=0), 1000) is None


def test_demand_is_left_alone():
    assert SE.tier_of(_row(watch=2), 1000) is None
    assert SE.tier_of(_row(sold=1), 1000) is None
    assert SE.tier_of(_row(s90=1), 1000) is None


def test_out_of_stock_wins_even_with_watchers():
    """在庫切れは買えないので、watcher が居ても落とす側。"""
    assert SE.tier_of(_row(qty=0, watch=9, sold=3), 1000) == SE.TIER_OOS


# ---- どこまで落とすか ----

def _shelf(r):
    return r["price"]


def test_picks_until_target_and_stops():
    rows = [_row(str(i), price=100.0) for i in range(10)]
    picked, total = SE.pick(rows, target=250, shelf_of=_shelf, shown_floor=1000)
    assert total >= 250 and len(picked) == 3          # 250 を超えた時点で止まる


def test_tier_order_beats_amount():
    """順位が上なら、金額が小さくても先に落とす。"""
    cheap_oos = _row("oos", qty=0, price=10.0)
    rich_nowatch = _row("rich", impr=5000, watch=0, price=900.0)
    picked, _ = SE.pick([rich_nowatch, cheap_oos], target=5, shelf_of=_shelf, shown_floor=1000)
    assert picked[0][1]["item_id"] == "oos"


def test_same_tier_orders_by_amount():
    small = _row("s", qty=0, price=10.0)
    big = _row("b", qty=0, price=900.0)
    picked, _ = SE.pick([small, big], target=5, shelf_of=_shelf, shown_floor=1000)
    assert picked[0][1]["item_id"] == "b"


def test_nothing_to_drop_returns_empty():
    picked, total = SE.pick([_row(watch=5)], target=1000, shelf_of=_shelf, shown_floor=1000)
    assert picked == [] and total == 0


# ---- 「見せた」と言える表示回数 ----

def test_shown_floor_is_median_of_in_stock():
    rows = [_row(str(i), impr=v) for i, v in enumerate([100, 2000, 4000, 6000, 8000])]
    assert SE.shown_floor_for(rows) == 4000


def test_shown_floor_never_below_the_hard_floor():
    rows = [_row(str(i), impr=v) for i, v in enumerate([1, 2, 3])]
    assert SE.shown_floor_for(rows) == SE.MIN_SHOWN_FLOOR


def test_shown_floor_ignores_out_of_stock():
    """在庫切れは検索から隠れて表示が伸びないので、基準の計算に混ぜない。"""
    rows = [_row("a", impr=4000), _row("b", qty=0, impr=1), _row("c", qty=0, impr=2)]
    assert SE.shown_floor_for(rows) == 4000
