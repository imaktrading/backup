# -*- coding: utf-8 -*-
"""ファネル分析は US だけを対象にする (2026-08-25 ユーザー指示)。

> ファネル分析スプシの各シートも US のみにしないとおかしいんじゃない？

UK / AU / CA は eBaymag が US の親出品から作るミラーで、**こちらから取り下げも修正も
できない** (グローバル CLAUDE.md「eBaymag のミラー — 直接 触るな」)。
混ぜると、手を出せない行がバケツを埋めて件数が意味を持たなくなる。

実測 2026-08-25 (ミラーを混ぜていた時):
```
DEAD_SIMPLE   2,055件 中 2,043件 がミラー   ← ほぼ全部
OUT_OF_STOCK  1,993件 中   887件
CULL          1,518件 中   867件
RESTOCK         475件 中    20件
```
US 限定にすると 4,820行 → 1,843行。CULL 651 / DEAD_SIMPLE 12。

★LQR (Listing quality report) は元々 US しか出ないので、NO_SEARCH / NO_CLICK /
  NO_CONVERT / RELIST / NEW_WAIT は前から 100% US だった。混ざっていたのは
  active レポート由来のバケツだけ。
"""
import os
import sys

import pytest

_HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TOOLS = os.path.join(_HQ, "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

_SRC = open(os.path.join(_TOOLS, "listing_funnel.py"), encoding="utf-8").read()


def test_mirrors_are_dropped_before_classification():
    """バケツに入る前に落とす (後から各タブで絞ると必ず漏れる)。"""
    assert 'rows = [r for r in rows if (r.get("site") or "").upper() == "US"]' in _SRC


def test_how_many_were_excluded_is_printed():
    """黙って減らさない。何件をなぜ外したか出す。"""
    assert "eBaymag のミラーを除外" in _SRC


def test_summary_says_us_only():
    """スプシの Summary タブを見た人が「US だけ」と分かること。"""
    assert "分析対象は **US のみ**" in _SRC
    assert "こちらから取り下げも修正もできない" in _SRC


def test_site_breakdown_is_kept_for_the_summary():
    """除外した内訳 (CA/UK/AU が何件か) は残す。消えたのか元々無いのか分かるように。"""
    assert "site_all = Counter" in _SRC


# ── 実データで確かめる ────────────────────────────────────────────
def _latest_funnel():
    import glob
    fs = glob.glob(os.path.join(_HQ, "funnel_output", "funnel_*.csv"))
    return max(fs, key=os.path.getmtime) if fs else None


def test_output_csv_is_us_only():
    """出力 CSV に非US が1行も無いこと (CULL/取下げ等 下流は全部これを読む)。"""
    import collections
    import csv
    f = _latest_funnel()
    if not f:
        pytest.skip("funnel CSV が無い環境")
    rows = list(csv.DictReader(open(f, encoding="utf-8")))
    sites = collections.Counter(r.get("site") for r in rows)
    assert set(sites) <= {"US"}, dict(sites)


def test_dead_simple_is_no_longer_a_mirror_dump():
    """DEAD_SIMPLE は元々「非US等・LQR無」の受け皿で、ミラーで埋まっていた。

    US 限定にすれば **LQR に載らない US 出品**だけが残る (本来の意味)。
    """
    import csv
    f = _latest_funnel()
    if not f:
        pytest.skip("funnel CSV が無い環境")
    rows = list(csv.DictReader(open(f, encoding="utf-8")))
    ds = [r for r in rows if "DEAD_SIMPLE" in (r.get("flags") or "")]
    assert all((r.get("site") or "").upper() == "US" for r in ds)
    # ミラーを混ぜていた頃は 2,000件超。US だけならごく少数のはず
    assert len(ds) < 200, f"DEAD_SIMPLE が {len(ds)}件 = まだミラーが混ざっている疑い"
