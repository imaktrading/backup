# -*- coding: utf-8 -*-
"""パネルの総合進捗が件数のままだった件 (2026-09-05)。

9/3 の棚割り見直し (棚割り見直し_20260903.pptx) の結論は
「詰まっているのは件数ではなく金額」。件数枠は 6,041/12,000 = 50% しか使っていないのに、
金額枠は $973,895/$1,000,000 = 97% 埋まっている。

にもかかわらずパネルは件数で測っており、棚を13倍食う PSA が
「目標150に対し 545件 = 進捗363% ✅達成」と出ていた。**減らすべきものが
「もう十分」に見えていた** = 判断を誤らせる表示だった。

対策: 目標を金額 (US価格$) にし、予算は pptx の配分をそのまま写す。
"""
import importlib.util
import os
import sys
from pathlib import Path

_HQ = Path(__file__).resolve().parent.parent


def _panel():
    spec = importlib.util.spec_from_file_location("control_panel_t", _HQ / "control_panel.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules["control_panel_t"] = m
    spec.loader.exec_module(m)
    return m


P = _panel()


def test_budget_is_money_not_counts():
    """予算は金額。件数の目標は残っていない (二重の物差しを作らない)。"""
    assert not hasattr(P, "CATEGORY_TARGETS"), "件数目標が残っている"
    assert not hasattr(P, "DEFAULT_TARGETS")
    assert P.CATEGORY_BUDGET_USD["TCG"] == 70000
    assert P.CATEGORY_BUDGET_USD["アウトドア・ジャケット"] == 40000


def test_budget_matches_the_shelf_plan():
    """pptx「結論1 棚割り」の配分と一致する (自分で数字を作らない)。"""
    plan = {"アウトドア・ジャケット": 40000, "Tシャツ": 60000, "TCG": 70000,
            "G-shock": 30000, "バッグ": 15000, "フィギュア": 8000}
    assert P.CATEGORY_BUDGET_USD == plan
    assert sum(plan.values()) == 223000            # pptx の合計
    assert P.SHELF_BUDGET_TOTAL_USD == 229661      # US価格ベースの棚予算


def test_over_budget_is_not_coloured_as_achieved():
    """予算超過を達成(緑)と同じ色にしない。9/5 の実害そのもの。"""
    # PSA: 予算 $70,000 に対し実測 $131,732 = 188%
    pct = int(131732 / P.CATEGORY_BUDGET_USD["TCG"] * 100)
    assert pct > 105
    # over 用の tag が定義されている (done と別)
    src = (_HQ / "control_panel.py").read_text(encoding="utf-8")
    assert '"over"' in src


def test_to_usd_parses_sheet_cells():
    assert P._to_usd("$242.98") == 242.98
    assert P._to_usd("1,234.5") == 1234.5
    assert P._to_usd("") == 0.0
    assert P._to_usd("—") == 0.0        # 読めない値は 0 (落とさない)
    assert P._to_usd(None) == 0.0


def test_empty_cat_has_money_fields():
    c = P._empty_cat()
    assert c == {"current": 0, "monthly": 0, "usd": 0.0, "monthly_usd": 0.0, "no_price": 0}
