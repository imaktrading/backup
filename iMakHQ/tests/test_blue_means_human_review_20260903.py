# -*- coding: utf-8 -*-
"""青 = **押さないと減らない残件がある** (2026-09-03 ユーザー確定)。

## なぜ
一度「青は目で見る作業だけ」に絞ったら、ユーザー指摘:

> 押さないと減らないのに黒文字だと、無意味
> 自動で消化されるのは、黒でいいけど

ユーザーは **青いものしか押さない**。押さないと減らない箱を黒にすると、
件数をヒントに出しても永遠に押されない = **機能を消したのと同じ**。

## 規則 (例外はこの1つだけ)
黒にしてよいのは **夜間バッチが勝手に減らしてくれるもの** = 探す系の4つ。
それも **夜が転んだ日は減らない**ので、その日は青に戻す
(黒のままだと自動が止まったことに誰も気づかず、溜まり続ける)。

夜に何が回るかは `tools/run_hoju_search.bat` が正。
"""
import os
import re

_HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = open(os.path.join(_HQ, "control_panel.py"), encoding="utf-8").read()
_LINES = _SRC[_SRC.index('act_kind = {'):].splitlines()
_END = next(i for i, ln in enumerate(_LINES) if '"kuji_refresh"' in ln)
_SEG = chr(10).join(_LINES[:_END + 1])   # 行単位 (値の中に {} が入る行がある)

# 夜間バッチが減らすもの = 黒でよい (ただし _auto が偽なら青)
_NIGHTLY = ("hoju_search", "ut_search", "ut_restock_search", "kuji_search")


def test_nothing_is_hardcoded_black():
    """`False` 固定の箱があると、そこは一生押されない。"""
    stuck = re.findall(r'"(\w+)":\s*False', _SEG)
    assert not stuck, "押さないと減らないのに黒固定: %s" % stuck


def test_every_button_is_blue_when_work_remains():
    """全部の箱が件数(bool)で色を決めている。"""
    kinds = re.findall(r'"(\w+)":', _SEG)
    for k in kinds:
        m = re.search(r'"%s":\s*(.+)' % k, _SEG)
        assert m.group(1).lstrip().startswith("bool("), k


def test_nightly_ones_go_black_only_while_the_batch_is_healthy():
    """夜が回っていれば黒、転んだ日は青。`not _auto` が消えたら溜まり続ける。"""
    assert "_auto = bool(nightly.get(\"ok\"))" in _SRC
    for k in _NIGHTLY:
        m = re.search(r'"%s":\s*(.+)' % k, _SEG)
        assert "not _auto" in m.group(1), k


def test_human_only_buttons_never_depend_on_the_nightly():
    """人が押さないと減らないものに `not _auto` を付けると、夜が元気な日に消える。"""
    kinds = [k for k in re.findall(r'"(\w+)":', _SEG) if k not in _NIGHTLY]
    assert len(kinds) >= 12, kinds
    for k in kinds:
        m = re.search(r'"%s":\s*(.+)' % k, _SEG)
        assert "_auto" not in m.group(1), k


def test_nightly_list_matches_the_batch_file():
    """黒にしてよい根拠は「夜に本当に回っているか」。bat と突き合わせる。"""
    bat = open(os.path.join(_HQ, "tools", "run_hoju_search.bat"),
               encoding="ascii", errors="replace").read()
    for frag in ("psa_hoju_fill.py search", "ut_hoju_fill.py search",
                 "ut_hoju_fill.py restock-search", "run_kuji_night.py"):
        assert frag in bat, frag
