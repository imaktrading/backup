# -*- coding: utf-8 -*-
"""同じ現物が2行あると「死んだ方の行」で在庫を判定していた件 (2026-09-05)。

ユーザー報告: 目視画面に「前に決めた答え」が何件も出る。出品されていれば出ないはずで、
出品されていないのはおかしい。

追跡した結果:
    cert152976751 (SB02-060) … 8/25〜9/5 の **13回**、毎回「仕入元が売り切れ」で
                                目視の後に捨てられていた
    cert150181360 (OP06-050) … 同じく6回 (8/31〜)
    どちらも **仕入元は生きていた** (実機で2回確認: in_stock)。

原因: 同じ cert がシートに2行あり、片方が売切(D列=○)。
    - 生成器 (psa_to_csv) は D列=○ の行を除外し、**生きている方の行**で CSV を作る
    - 入稿直前の在庫判定 (supply_index) は `setdefault` = **先に出てきた行が勝ち**
      だったため、売切の方の行を見て「仕入元が売り切れ」と落としていた
= 生成と判定が別の行を見ていた。行が重複している cert は実測54件 (未出品どうし35件)。
"""
import os
import sys

_TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import csv_drop_sold_rows as CD  # noqa: E402

NCOL = 20
DEAD = "https://jp.mercari.com/shops/product/2JTeKjrSCj9PyYQSZfUvXj"
LIVE = "https://jp.mercari.com/shops/product/2JUbFPiFLAmm4yLu6rDaZy"


def _row(url="", cert="", sold="", checked="2026-09-05"):
    r = [""] * NCOL
    r[CD.A], r[CD.I], r[CD.D], r[CD.O] = url, cert, sold, checked
    return r


def _sheet(*rows):
    return [[f"c{i}" for i in range(NCOL)]] + list(rows)


def test_live_row_wins_when_the_sold_one_comes_first():
    """9/5 の実データそのもの: 売切の行が先、生きている行が後。"""
    vals = _sheet(_row(DEAD, "152976751", sold="○"),
                  _row(LIVE, "152976751"))
    got = CD.supply_index(vals)["152976751"]
    assert got["sold"] is False
    assert got["url"] == LIVE
    assert got["row"] == 3


def test_live_row_wins_when_it_comes_first_too():
    """順番に依存しない。"""
    vals = _sheet(_row(LIVE, "152976751"),
                  _row(DEAD, "152976751", sold="○"))
    got = CD.supply_index(vals)["152976751"]
    assert got["sold"] is False and got["url"] == LIVE


def test_all_sold_stays_sold():
    """両方売切なら売切のまま。生きているように見せない (fail-closed)。"""
    vals = _sheet(_row(DEAD, "111", sold="○"), _row(LIVE, "111", sold="○"))
    assert CD.supply_index(vals)["111"]["sold"] is True


def test_row_with_a_url_wins_over_an_empty_one():
    vals = _sheet(_row("", "111"), _row(LIVE, "111"))
    assert CD.supply_index(vals)["111"]["url"] == LIVE


def test_single_row_is_unchanged():
    vals = _sheet(_row(LIVE, "111", sold="○", checked="2026-09-01"))
    got = CD.supply_index(vals)["111"]
    assert got == {"sold": True, "checked": "2026-09-01", "url": LIVE, "row": 2}


def test_supply_id_key_follows_the_same_rule():
    """URL末尾を鍵にした引き方でも、生きている行を採る。"""
    vals = _sheet(_row(DEAD, "111", sold="○"), _row(DEAD, "222"))
    import sheet_io
    sid = sheet_io.supply_id_from_url(DEAD)
    assert sid, "supply_id が取れないとこの test は意味を持たない"
    assert CD.supply_index(vals)[sid]["sold"] is False
