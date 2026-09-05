# -*- coding: utf-8 -*-
"""同定済みの予備仕入元が行き先なしで寝ていた件 (2026-09-05)。

捨てた候補を人が同定し直して「新規出品候補」タブに積む所までは出来ていたが、
**用途=補URL(2枚目以降) の行には行き先が書かれていなかった** (画面の案内も
「貼り付けるのは『用途=出品』の行だけ」としか言っていない)。

実測 (2026-09-05):
    新規出品候補 タブ 183件 / うち補URL用 163件 / 未転記 159件
    同じ日に「補URLが1本も無い出品 45件」

カードの同定は人が済ませているので新しい判断は要らない = 機械で入れてよい。
適用後: 補0本 45件 → 38件 / 補≤1本 209件 → 194件。
"""
import os
import sys

_HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TOOLS = os.path.join(_HQ, "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import psa_hoju_fill as H  # noqa: E402

_BAT = open(os.path.join(_TOOLS, "run_hoju_search.bat"), encoding="utf-8").read()
NCOL = 40
U = "https://jp.mercari.com/item/m%d"


def _tab(*rows):
    head = ["用途", "HIGH転記", "A列:仕入元URL", "C列:タイトル", "M列:仕入価格(円)",
            "I列:cert", "R列:カテゴリ", "AI列:KEY", "product_id", "元itemID", "日付"]
    return [head] + [list(r) for r in rows]


def _cand(use, done, url, price, key):
    return [use, done, url, "title", price, "", "TCG", key, "pid", "111", "2026-09-05"]


def _sheet_row(iid, key, main="", aux=(), sold=""):
    r = [""] * NCOL
    r[H.A] = main
    r[H.B] = iid
    r[H.D] = sold
    r[H.CATEGORY] = "TCG"
    r[H.KEY] = key
    for i, u in enumerate(aux):
        r[H.AUX0 + i] = u
    return r


def _vals(rows):
    return [[f"c{i}" for i in range(NCOL)]] + rows


# ------------------------------------------------ 拾う行の条件

def test_only_aux_rows_that_are_not_done_are_picked():
    t = _tab(_cand(H.NEWCAND_USE_AUX, "", U % 1, 900, "k1"),
             _cand(H.NEWCAND_USE_AUX, "済(補URL)", U % 2, 800, "k1"),   # 転記済
             _cand("出品", "", U % 3, 700, "k2"),                        # 用途が違う
             _cand(H.NEWCAND_USE_AUX, "", U % 4, 600, ""))              # KEY 無し
    p = H.pending_newcand_aux(t)
    assert p == {"k1": [(U % 1, 900)]}, p


def test_price_that_cannot_be_read_becomes_none():
    t = _tab(_cand(H.NEWCAND_USE_AUX, "", U % 1, "", "k1"))
    assert H.pending_newcand_aux(t) == {"k1": [(U % 1, None)]}


# ------------------------------------------------ どの出品に入れるか

def test_target_is_the_listing_with_fewest_backups():
    """同じKEYが複数あるなら、補が薄い方に入れる (丸腰から埋める)。"""
    vals = _vals([_sheet_row("a", "k1", aux=(U % 8, U % 9)),
                  _sheet_row("b", "k1", aux=())])
    assert H.live_rows_by_key(vals)["k1"] == 3        # 行3 = itemID 'b'


def test_sold_and_unlisted_rows_are_not_targets():
    vals = _vals([_sheet_row("", "k1"), _sheet_row("b", "k2", sold="売切")])
    assert H.live_rows_by_key(vals) == {}


# ------------------------------------------------ 書込計画

def test_cheaper_candidate_is_written_in_order():
    vals = _vals([_sheet_row("a", "k1", main=U % 1, aux=(U % 7,))])
    pend = {"k1": [(U % 5, 300)]}
    wb, used, skipped = H.plan_newcand_aux(pend, vals, {}, guard_ok=True)
    assert wb == {2: [U % 5, U % 7]}, wb          # 値段の分かる方が先
    assert not skipped


def test_main_supply_url_is_not_duplicated_into_aux():
    """主URL(A列)と同じ物を補に入れても厚みにならない。"""
    vals = _vals([_sheet_row("a", "k1", main=U % 5)])
    wb, _used, skipped = H.plan_newcand_aux({"k1": [(U % 5, 300)]}, vals, {}, guard_ok=True)
    assert wb == {}
    assert "主URL" in skipped["k1"]


def test_url_used_by_another_listing_is_dropped():
    vals = _vals([_sheet_row("a", "k1")])
    owner = {U % 5: ["222"]}
    wb, _used, skipped = H.plan_newcand_aux({"k1": [(U % 5, 300)]}, vals, owner, guard_ok=True)
    assert wb == {}
    assert "他出品が使用中" in skipped["k1"]


def test_nothing_is_written_when_the_guard_is_not_ready():
    """ガードを組めなければ1行も書かない (fail-closed)。"""
    vals = _vals([_sheet_row("a", "k1")])
    wb, used, skipped = H.plan_newcand_aux({"k1": [(U % 5, 300)]}, vals, {}, guard_ok=False)
    assert wb == {} and used == set()
    assert skipped == {"k1": "URL共有ガードを組めず中止"}


def test_key_without_a_live_listing_is_reported_not_dropped_silently():
    vals = _vals([_sheet_row("a", "other")])
    wb, _used, skipped = H.plan_newcand_aux({"k1": [(U % 5, 300)]}, vals, {}, guard_ok=True)
    assert wb == {}
    assert "対応する出品が無い" in skipped["k1"]


# ------------------------------------------------ 夜間に回す

def test_batch_runs_newcand_aux():
    assert "psa_hoju_fill.py newcand-aux" in _BAT
