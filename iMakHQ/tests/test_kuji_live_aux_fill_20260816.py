# -*- coding: utf-8 -*-
"""一番くじ: 生きている出品の補URL補充 (2026-08-16 ユーザー要望)。

★なぜ要るか: 従来の一番くじは「売り切れてから代わりの仕入元を探す」事後型だけで、
  PSA のような「切れる前に予備を貯める」経路が無かった。補URL は仕入元が消えた時の
  保険なので、切れてから貯めても保険にならない。
  実測 (2026-08-16 商品管理シート): live 30件のうち **補URL 0本が10件**。

★ここで守ること (壊すと出品事故になる):
  1. live 行の A列(現supply) / B列(itemID) / D列(売り切れ) を **書かない**
     (書くと eBay 出品との紐付けが切れ、取下げ漏れ or 二重出品になる)
  2. 既に貯めてある補URLを **消さない** (AC-AG は5枠まるごと上書きなので、
     新しい分だけ渡すと既存が消える)
  3. **他の出品が使っている仕入元URLを掴まない** (両方売れたら片方が履行不能
     → キャンセル → Defect)。判定できない時は書かない (fail-closed)
"""
from __future__ import annotations

import importlib.util
import os
import sys

_TOOLS = r"C:\dev\iMak\iMakHQ\tools"


def _load(name, fname):
    spec = importlib.util.spec_from_file_location(name, os.path.join(_TOOLS, fname))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    if _TOOLS not in sys.path:
        sys.path.insert(0, _TOOLS)
    spec.loader.exec_module(mod)
    return mod


K = _load("_hq_kuji_restock_aux", "ichibankuji_restock.py")


def _row(item_id, a="", aux=(), sold="", cat="一番くじ"):
    r = [""] * 40
    r[0], r[1], r[3], r[17] = a, item_id, sold, cat
    for i, u in enumerate(aux):
        r[K.AUX_COL0 + i] = u
    return r


def test_existing_aux_is_kept():
    """既存の補URLを消さない。空き枠にだけ足す。"""
    vals = [[], _row("358a", a="https://jp.mercari.com/item/m1",
                     aux=["https://jp.mercari.com/item/m2"])]
    rows = {2: {"kind": "live_thin", "aux": ["https://jp.mercari.com/item/m3"]}}
    plan, added, dropped = K.plan_live_aux(rows, vals, {})
    assert plan[2][:2] == ["https://jp.mercari.com/item/m2",
                           "https://jp.mercari.com/item/m3"], plan
    assert added == 1 and not dropped


def test_url_used_by_another_listing_is_dropped():
    """他の出品が使っている仕入元は掴まない (両売れ → 履行不能 → Defect)。"""
    used = "https://jp.mercari.com/item/m9"
    vals = [[], _row("358a"), _row("358b", a=used)]
    owner = K.build_owner_by_url(vals)
    rows = {2: {"kind": "live_thin", "aux": [used, "https://jp.mercari.com/item/m4"]}}
    plan, added, dropped = K.plan_live_aux(rows, vals, owner)
    assert [u for u, _o in dropped] == [used]
    assert plan[2][0] == "https://jp.mercari.com/item/m4" and added == 1


def test_sold_rows_do_not_reserve_urls():
    """売り切れ行が持っているURLは「使用中」に数えない (もう出品が生きていない)。"""
    u = "https://jp.mercari.com/item/m7"
    vals = [[], _row("358z", a=u, sold="○")]
    assert K.build_owner_by_url(vals) == {}


def test_live_rows_never_touch_a_b_d_columns():
    """live 行は A/B/D/M を1セルも書かない (書くと出品との紐付けが切れる)。"""
    reqs = K.build_restock_reqs({2: {"kind": "live_thin", "a": "x", "b": "358a",
                                     "cost": 1000, "aux": ["u"]}})
    assert reqs == [], reqs


def test_nothing_added_means_no_write():
    """足すものが無い行は書込計画に入れない (無駄な上書きをしない)。"""
    u = "https://jp.mercari.com/item/m2"
    vals = [[], _row("358a", aux=[u])]
    plan, added, _ = K.plan_live_aux({2: {"kind": "live_thin", "aux": [u]}}, vals, {})
    assert plan == {} and added == 0


def test_live_target_uses_all_five_slots():
    """補充対象は「補URLが5本未満の live」。0本の行だけではない。"""
    src = open(os.path.join(_TOOLS, "ichibankuji_restock.py"), encoding="utf-8").read()
    assert "get_thin_backup_ichibankuji(n, max_backups=AUX_MAX) if live" in src


def test_button_and_nightly_are_wired():
    """夜に候補を貯め、昼にボタンで目視する2段が実際につながっていること。"""
    panel = open(r"C:\dev\iMak\iMakHQ\control_panel.py", encoding="utf-8").read()
    assert '"ichibankuji_restock.py", "hoju", "10"' in panel, "目視ボタンが無い"
    bat = open(os.path.join(_TOOLS, "run_hoju_search.bat"), encoding="ascii").read()
    assert "ichibankuji_restock.py prefetch-live" in bat, "夜間の候補集めが無い"
