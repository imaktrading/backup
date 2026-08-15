# -*- coding: utf-8 -*-
"""空振りが続く対象を毎晩の枠から外す (2026-08-15)。

★ユーザー指摘「全然減らない気がする」。実測 8/09〜8/15 の7日間、補0本は 41〜46件で横ばい。
  毎晩30件を叩いているのに埋まらない。夜間ログを見ると **同じカードが7日連続**で並び
  (OP04-024 / OP01-024 / OP07-085 / OP10-111 / OP01-061 / OP01-016)、毎晩
  「多変種で変種確証不可」または絵柄不一致で候補ゼロ。= その版が市場に無いカードを
  毎晩探し直し、30枠の半分以上を食っていた。

絵柄判定は正しい (実測 same 514 / different 199、理由も具体的) ので緩めない。
**枠の使い方**を変える: 連続空振りは間隔を空け、空いた枠を未探索に回す。

固定する挙動:
  1. 3夜連続で候補ゼロなら、毎晩の枠から外す
  2. ただし捨てない。7日おきに必ず戻る (供給は後から湧く)
  3. 候補が1件でも出たら streak は 0 に戻る
  4. 台帳が無い/壊れていても落ちない
"""
from __future__ import annotations

import sys

_TOOLS = r"C:\dev\iMak\iMakHQ\tools"
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import psa_hoju_fill as H  # noqa: E402


def _streak(n, last):
    return {"streak": n, "last": last}


def test_skips_after_three_dry_nights():
    assert H.should_skip_dry(_streak(3, "2026-08-15"), "2026-08-16") is True
    assert H.should_skip_dry(_streak(2, "2026-08-15"), "2026-08-16") is False


def test_comes_back_after_a_week():
    """捨てない。7日経てば必ず再挑戦する (供給は後から湧く)。"""
    assert H.should_skip_dry(_streak(9, "2026-08-01"), "2026-08-09") is False


def test_no_entry_is_never_skipped():
    assert H.should_skip_dry(None, "2026-08-16") is False
    assert H.should_skip_dry({}, "2026-08-16") is False


def test_hit_resets_the_streak():
    d = H.update_dry({}, "358a", False, "2026-08-13")
    d = H.update_dry(d, "358a", False, "2026-08-14")
    assert d["358a"]["streak"] == 2
    d = H.update_dry(d, "358a", True, "2026-08-15")
    assert d["358a"]["streak"] == 0


def test_broken_ledger_does_not_crash(tmp_path):
    p = tmp_path / "broken.json"
    p.write_text("{ not json", encoding="utf-8")
    assert H.load_dry(str(p)) == {}
    assert H.load_dry(str(tmp_path / "missing.json")) == {}


def test_night_search_filters_before_the_limit():
    """★limit を切る前に間引く。後で切ると空振り分が枠を食ったままになる。"""
    src = open(r"C:\dev\iMak\iMakHQ\tools\psa_hoju_fill.py", encoding="utf-8").read()
    i_dry = src.index("空振り続き")
    i_lim = src.index("todo = todo[:limit]", src.index("def run_night_search"))
    assert i_dry < i_lim, "間引きが limit の後に来ている"
