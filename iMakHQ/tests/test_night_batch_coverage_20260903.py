# -*- coding: utf-8 -*-
"""夜にできることは夜に回す (2026-09-03)。

## なぜ
ユーザー要望「夜間に出来る部分は全てバッチに回して、時短にして」。
朝ボタンを押してから探し始めるので待たされていた。夜に候補を溜めておけば、
朝は **目視だけ** になる。

## 夜に回してよいもの / いけないもの
回してよい … 候補を集めるだけ / レポートを読んでスプシに書くだけ (無人で完結)
回さない   … **eBay に書くもの**。取下げ・再出品・数量戻しは取り返しがつかないので
             人がボタンを押す。誤って一括で走らせない。
"""
import io
import os
import re

_TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
_BAT = io.open(os.path.join(_TOOLS, "run_hoju_search.bat"),
               encoding="ascii", errors="replace").read()


def _runs(script):
    return re.search(r"python -u %s\b" % re.escape(script), _BAT) is not None


def test_ut_is_in_the_night_batch():
    """UT は補URLも再仕入れも夜に探す (朝は目視だけ)。"""
    assert "ut_hoju_fill.py search" in _BAT
    assert "ut_hoju_fill.py restock-search" in _BAT


def test_ut_night_steps_do_not_write_to_the_sheet():
    """夜は貯めるだけ。confirm (目視して書く) は夜に走らせない。"""
    assert "ut_hoju_fill.py confirm" not in _BAT
    assert "ut_hoju_fill.py restock-confirm" not in _BAT


def test_analyses_run_at_night():
    """朝のボタンが新しい数字で判断できるように、ファネルと分析を先に回す。"""
    for s in ("listing_funnel.py", "funnel_diff.py", "demand_winners.py",
              "restock_worklist.py", "run_kuji_night.py"):
        assert _runs(s), s


def test_nothing_that_writes_to_ebay_runs_at_night():
    """取下げ・再出品・数量戻しは人が押す。夜に混ぜない。"""
    for s in ("cull_end.py", "shelf_evict.py", "sold_restock.py",
              "relist_from_funnel.py", "relist_add_from_pending.py",
              "relist_writeback.py", "psa_restock_writeback.py",
              "ebay_upload_csv.py"):
        assert not _runs(s), f"eBay に書くものが夜間バッチに入っている: {s}"


def test_no_visual_confirm_runs_at_night():
    """目視の画面を無人で開かない (誰も見ないまま待ち続ける)。"""
    assert not _runs("newcand_confirm.py")
    # PSA の目視は --dry-run (画面を出さず、翌朝の下ごしらえだけ) なら可
    m = re.search(r"psa_hoju_fill\.py confirm([^\r\n]*)", _BAT)
    assert m and "--dry-run" in m.group(1)


def test_bat_stays_ascii_only():
    """cmd は OEM codepage で読む。日本語を入れると全部壊れる (2026-07-30 実害)。"""
    raw = open(os.path.join(_TOOLS, "run_hoju_search.bat"), "rb").read()
    assert all(b < 0x80 for b in raw)
