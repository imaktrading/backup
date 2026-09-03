# -*- coding: utf-8 -*-
"""青は「人が目で見る作業」だけ (2026-09-03)。

## なぜ
ユーザー指摘「青いボタンが多くて、忙しい」。青 = 「今これを押す」の合図なのに
**17個**が青になり得て、合図として死んでいた。

## 絞り方
青にする   … **人にしかできない目視** と、その日にしか押せない当日分
青にしない … ① 夜間バッチが回すもの (探す系)
             ② 目視の続き (CSVを作る / 戻ったか確認)
             ③ 押すかを自分で決める操作 (取下げ / 棚 / 売れた分の補充)
             件数はヒントに出るので、見たい時は見られる。

夜が転んだ時は **目視の件数が0のまま**なので、そこで気づける。
"""
import os
import re

_HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = open(os.path.join(_HQ, "control_panel.py"), encoding="utf-8").read()
_SEG = _SRC[_SRC.index("act_kind = {"):][:3200]

_BLUE = {m.group(1) for m in re.finditer(r'"(\w+)":\s*bool\(', _SEG)}
_BLACK = {m.group(1) for m in re.finditer(r'"(\w+)":\s*False', _SEG)}


def test_search_buttons_are_never_blue():
    """夜間バッチが回すので、朝に押す合図を出さない。"""
    for k in ("ut_search", "ut_restock_search", "kuji_search"):
        assert k in _BLACK, k


def test_irreversible_actions_are_not_blue():
    """取下げ・棚・売れた分の補充は、押すかを自分で決める操作。"""
    for k in ("cull_end", "shelf_evict", "sold_restock"):
        assert k in _BLACK, k


def test_follow_up_steps_are_not_blue():
    """②CSV / ③確認 は目視の続き。目視を終えれば自然に押す。"""
    for k in ("restock_build", "restock_wb", "kuji_refresh"):
        assert k in _BLACK, k


def test_human_review_steps_stay_blue():
    """人にしかできない目視は青のまま (ここが詰まると全部止まる)。"""
    for k in ("hoju_confirm", "ut_confirm", "ut_restock_confirm",
              "kuji_confirm", "psa_gate", "kuji_supply"):
        assert k in _BLUE, k
    assert "hoju_search" in _BLUE      # 🆕 当日分 = 出品直後にしか押せない


def test_blue_stays_a_small_set():
    """合図として効く数に保つ。増やす時は本当に「今押す」ものか考える。"""
    assert len(_BLUE) <= 8, sorted(_BLUE)
