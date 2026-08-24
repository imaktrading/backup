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
    assert "rows, _n_mirror, _n_gained = absorb_mirror_demand(rows)" in _SRC


def test_how_many_were_excluded_is_printed():
    """黙って減らさない。何件をなぜ外したか出す。"""
    assert "eBaymag のミラー" in _SRC and "を除外" in _SRC


def test_summary_says_us_only():
    """スプシの Summary タブを見た人が「US だけ」と分かること。"""
    assert "分析対象は **US のみ**" in _SRC
    assert "こちらから取り下げも修正もできない" in _SRC


def test_site_breakdown_is_kept_for_the_summary():
    """除外した内訳 (CA/UK/AU が何件か) は残す。消えたのか元々無いのか分かるように。"""
    assert "_mirror_sites = dict(Counter(" in _SRC


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


# ── ミラーの需要は捨てずに親へ足す (2026-08-25) ────────────────────
# > 確かに US以外のニーズを無視しているね
#
# ミラーは触れないので行動対象から外すのは正しいが、そこで付いた watcher と売上は
# 本物の需要。捨てると「US で誰も見ていない商品」が需要ゼロ = 取り下げ候補に落ちる。
# 実測 2026-08-23: ミラー 2,977件 中 需要シグナル 67件、うち 39件は US 親が 0 だった。


def _F():
    import listing_funnel
    return listing_funnel


def test_watchers_and_sales_roll_up_to_the_parent():
    F = _F()
    rows = [{"site": "US", "title": "Card A", "sold_qty": 0, "watch": 0, "sales90": 0},
            {"site": "UK", "title": "Card A", "sold_qty": 1, "watch": 5, "sales90": 0},
            {"site": "AU", "title": "Card A", "sold_qty": 0, "watch": 2, "sales90": 3}]
    us, n_mirror, n_gained = F.absorb_mirror_demand(rows)
    assert len(us) == 1 and n_mirror == 2 and n_gained == 1
    assert us[0]["sold_qty"] == 1 and us[0]["watch"] == 7 and us[0]["sales90"] == 3


def test_mirror_without_a_parent_is_just_dropped():
    """親が見つからないミラーの需要は **どこにも足さない** (作り話をしない)。"""
    F = _F()
    rows = [{"site": "US", "title": "Card A", "sold_qty": 0, "watch": 0, "sales90": 0},
            {"site": "CA", "title": "Card X", "sold_qty": 0, "watch": 9, "sales90": 0}]
    us, _n, gained = F.absorb_mirror_demand(rows)
    assert us[0]["watch"] == 0 and gained == 0


def test_no_demand_no_change():
    """需要ゼロのミラーは何も足さない (件数だけ数える)。"""
    F = _F()
    rows = [{"site": "US", "title": "A", "sold_qty": 0, "watch": 0, "sales90": 0},
            {"site": "UK", "title": "A", "sold_qty": 0, "watch": 0, "sales90": 0}]
    us, n_mirror, gained = F.absorb_mirror_demand(rows)
    assert n_mirror == 1 and gained == 0 and us[0]["watch"] == 0


def test_exposure_is_not_rolled_up():
    """露出 (impr/CTR) は LQR が US しか出さないので足さない (足すと嘘になる)。"""
    F = _F()
    import inspect
    src = inspect.getsource(F.absorb_mirror_demand)
    assert '("sold_qty", "sales90", "watch")' in src
    assert "impr" not in src.split('"""')[2]      # 実装部に impr を触る行が無い


def test_title_key_matches_mirror_to_parent():
    F = _F()
    assert F._title_key("PSA 10 One Piece — Card!") == F._title_key("psa10onepiececard")


def test_funnel_reports_how_much_was_absorbed():
    """黙って足さない。何件の US 行に上乗せしたか出す。"""
    src = open(os.path.join(_TOOLS, "listing_funnel.py"), encoding="utf-8").read()
    assert "件の US 行に上乗せ" in src
