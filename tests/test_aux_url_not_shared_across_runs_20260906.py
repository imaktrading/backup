# -*- coding: utf-8 -*-
"""1本の仕入元を2出品の補URLにしない — 走行をまたいでも (2026-09-06)。

従来のガードは `assigned` (その走行の中だけ)。付ける先の行の中身しか照合しないので、
**別の日に走ると同じURLが別の出品にも付く**。
実害 (2026-09-06 の入稿ログ): `m80392401851` が 820034256174 と 820034337348 の
両方の補URLに入り、dup_guard が「★① 仕入元URL共有 = 両方売れたら履行不能」と検出した。
無在庫では履行不能 → キャンセル → Defect Rate → アカウント毀損に直結する。
"""
import os
import sys

_TOOLS = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "iMakHQ", "tools"))
sys.path.insert(0, _TOOLS)

import hoju_url_from_dupes as H   # noqa: E402

N = 40
HDR = ["h"] * N
URL = "https://jp.mercari.com/item/m999"
OTHER = "https://jp.mercari.com/item/m888"


def _row(a="", b="", d="", cert="", key="", aux=()):
    r = [""] * N
    r[H.A], r[H.B], r[H.D], r[H.I], r[H.KEY] = a, b, d, cert, key
    for i, u in enumerate(aux):
        r[H.AUX0 + i] = u
    return r


def test_url_already_used_by_another_listing_is_not_added():
    """他の出品が既に持っているURLは足さない (今回の事故そのもの)。"""
    rows = [HDR,
            _row(b="111", cert="c1", key="k1", aux=(URL,)),   # 既に URL を持つ live
            _row(b="222", cert="c2", key="k1"),               # 同じカードの別 live (空)
            _row(a=URL, cert="c3", key="k1")]                 # 2枚目 = この URL が出どころ
    plan, warns = H.compute_additions(rows, live_ids={"111", "222"})
    assert all(not v["add"] for v in plan.values())
    assert any("既に他の出品" in w for w in warns)


def test_unused_url_is_still_added():
    """使われていないURLは今まで通り足す (塞ぎすぎない)。"""
    rows = [HDR,
            _row(b="111", cert="c1", key="k1"),
            _row(a=OTHER, cert="c2", key="k1")]
    plan, _ = H.compute_additions(rows, live_ids={"111"})
    assert [v["add"] for v in plan.values()] == [[OTHER]]


def test_same_listing_keeping_its_own_url_is_not_blocked():
    """持ち主が付ける先の出品自身なら、ブロックしない (自分の枠は自分で使える)。"""
    rows = [HDR,
            _row(a=URL, b="111", cert="c1", key="k1"),   # A列に同じURL = 自分の主仕入元
            _row(a=URL, cert="c2", key="k1")]
    plan, warns = H.compute_additions(rows, live_ids={"111"})
    # 主仕入元と同じURLなので「既存」扱いで skip されるのが正 (他人の使用ではない)
    assert not any("既に他の出品" in w for w in warns)


def test_unlisted_rows_do_not_reserve_a_url():
    """未出品の行はURLを押さえない (これから使う側なので塞いだら誰も使えない)。"""
    rows = [HDR,
            _row(b="111", cert="c1", key="k1"),
            _row(a=URL, cert="c2", key="k1"),            # 未出品 (B空)
            _row(a=URL, cert="c3", key="k1")]            # 同じURLの未出品がもう1行
    plan, _ = H.compute_additions(rows, live_ids={"111"})
    assert [v["add"] for v in plan.values()] == [[URL]]


def test_url_normalisation_catches_variants():
    """クエリ付き/末尾スラッシュ違いでも同じURLと見なす (すり抜け防止)。"""
    rows = [HDR,
            _row(b="111", cert="c1", key="k1", aux=(URL + "?utm=1",)),
            _row(b="222", cert="c2", key="k1"),
            _row(a=URL, cert="c3", key="k1")]
    plan, warns = H.compute_additions(rows, live_ids={"111", "222"})
    assert all(not v["add"] for v in plan.values())
    assert any("既に他の出品" in w for w in warns)
