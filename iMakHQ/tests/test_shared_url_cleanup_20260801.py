"""共有された仕入元URLを補URL側から自動で外す (2026-08-01 実害).

実害: itemID 358571988846 と 358849557595 が同じ mercari Shops URL を指していた。
両方 live・同じ OP13-004 サボ = **片方が売れたらもう片方は履行不能** → キャンセル → Defect。

★入口ガードでは防げない構造:
  `hoju_url_from_dupes` は「重複くんが弾いた2枚目の A列URL」を primary の補URLに足す。
  2枚目は書いた時点で itemID 空 (未出品) なので誰とも衝突していない。
  **その2枚目が後日出品されると危険化する**。だから検出時に外す reconciliation が要る。

守りたい性質:
  1. 外すのは補URL側だけ。**主URL(A) は絶対に触らない**
  2. 対象は「別の ACTIVE 行がその URL を主URLに持つ」補URLのみ (補URL どうしの重複は触らない)
  3. 自分自身が主URLに持つ URL は外さない
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import dup_guard as dg  # noqa: E402

A, B, D = dg.A, dg.B, dg.D
AUX0, AUXN = dg.AUX0, dg.AUXN


def _row(itemid="", url="", aux=(), sold=""):
    r = [""] * 45
    r[B], r[A], r[D] = itemid, url, sold
    for i, u in enumerate(aux):
        r[AUX0 + i] = u
    return r


HDR = [""] * 45
U1 = "https://jp.mercari.com/shops/product/AAA"
U2 = "https://jp.mercari.com/shops/product/BBB"


def test_aux_matching_another_primary_is_dropped():
    """実害ケース: 他出品の主URL が自分の補URLに入っている。"""
    rows = [HDR,
            _row("111", U1, aux=[U2]),        # 111 の補URL = 222 の主URL
            _row("222", U2)]
    plan = dg.plan_shared_url_cleanup(rows)
    assert list(plan) == [2]
    assert plan[2]["drop"] == [U2]
    assert plan[2]["keep"] == []
    assert plan[2]["owner"][U2] == "222"


def test_primary_url_is_never_touched():
    """主URL は出品の供給そのもの。外すと出品が死ぬので絶対に触らない。"""
    rows = [HDR, _row("111", U1), _row("222", U1, aux=[])]   # 主URL どうしの衝突
    plan = dg.plan_shared_url_cleanup(rows)
    assert plan == {}, "主URL を drop 対象にしてはいけない (人が判断する領域)"


def test_aux_to_aux_overlap_is_left_alone():
    """補URL どうしの重複は、実際に売れるまで履行不能にならない → 過剰除去しない。"""
    rows = [HDR, _row("111", U1, aux=[U2]), _row("222", "https://x/other", aux=[U2])]
    plan = dg.plan_shared_url_cleanup(rows)
    assert plan == {}


def test_own_primary_in_own_aux_is_kept():
    """自分の主URL が自分の補URLにもある場合は他出品と衝突しない。"""
    rows = [HDR, _row("111", U1, aux=[U1])]
    assert dg.plan_shared_url_cleanup(rows) == {}


def test_sold_rows_are_ignored():
    """取下げ済 (D=○) は ACTIVE でないので衝突源にならない。"""
    rows = [HDR, _row("111", U1, aux=[U2]), _row("222", U2, sold="○")]
    assert dg.plan_shared_url_cleanup(rows) == {}


def test_keep_preserves_safe_aux():
    """危険な1本だけ外し、安全な補URLは残す (供給を無駄に削らない)。"""
    safe = "https://jp.mercari.com/shops/product/SAFE"
    rows = [HDR, _row("111", U1, aux=[U2, safe]), _row("222", U2)]
    plan = dg.plan_shared_url_cleanup(rows)
    assert plan[2]["drop"] == [U2]
    assert plan[2]["keep"] == [safe]


def test_audit_wires_the_cleanup():
    """検出して終わりにせず、監査から実際に是正を呼ぶこと。"""
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "tools", "dup_guard.py"), encoding="utf-8").read()
    assert "plan_shared_url_cleanup(vals)" in src
    assert "write_aux_urls" in src
