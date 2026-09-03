# -*- coding: utf-8 -*-
"""PSA と G-shock に 仕入 ¥7万 の上限を効かせる (2026-09-04 ユーザー指示)。

## なぜ G-shock は別に手当てが要ったか
上限の判定 (pricing_engine.cost_sanity) は全カテゴリ共通だが、**効く場所**が違った:
  PSA    … 生成時に `<CSV>_cost.json` を書くので、CSV監査くん / check_csv が
           cost を読めて門が働く (¥1,111,111 を実際に止めた実績あり)
  G-shock… **cost の sidecar を書いていない** → 後段は cost を読めず、
           門が付いているのに **一度も働かない** 状態だった
→ G-shock は「価格を決める直前」に置く。ここが唯一 cost を持っている場所。

## 実測 (funnel_20260904 / Wristwatches 230件)
  〜¥2万 135件 売れた5件 / ¥2–3万 46件 1件 / ¥3–5万 40件 0件 / ¥5–7万 9件 0件
  ¥7万超は **そもそも1件も出していない** → 今の運用では何も外れない。
  10万超を仕入れようとした時に初めて止まる位置づけ。
"""
import io as _io
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if os.path.join(_ROOT, "iMakeBayAPI") not in sys.path:
    sys.path.insert(0, os.path.join(_ROOT, "iMakeBayAPI"))

from pricing_engine import cost_sanity                         # noqa: E402


def test_the_cap_value():
    assert cost_sanity(69999) is None
    assert cost_sanity(70001)


def test_gshock_stops_before_making_the_row():
    """作ってから監査で外すのではなく、生成しない (Selenium を無駄に回さない)。"""
    s = _io.open(os.path.join(_ROOT, "iMakG-shock", "gshock_to_csv.py"),
                 encoding="utf-8").read()
    i = s.index("cost_jpy = COST_JPY_FALLBACK")
    j = s.index("ebay_median = 0.0", i)
    seg = s[i:j]
    assert "cost_sanity" in seg, "価格を決める前に上限を見ていない"
    assert "continue" in seg, "上限超の行を作ってしまっている"


def test_gshock_does_not_silently_shrink():
    """外した分は必ず出す (黙って件数が減ると気づけない)。"""
    s = _io.open(os.path.join(_ROOT, "iMakG-shock", "gshock_to_csv.py"),
                 encoding="utf-8").read()
    assert "skipped_cost" in s
    assert "仕入値が上限超で出品しなかった" in s


def test_gshock_fallback_cost_is_under_the_cap():
    """価格が全部空の時の推定値が上限を超えていたら、全件落ちてしまう。"""
    s = _io.open(os.path.join(_ROOT, "iMakG-shock", "gshock_to_csv.py"),
                 encoding="utf-8").read()
    v = int([ln for ln in s.split(chr(10))
             if ln.startswith("COST_JPY_FALLBACK")][0].split("=")[1].split("#")[0].strip())
    assert cost_sanity(v) is None, "推定値が上限に引っかかると1件も出せない"


def test_psa_paths_are_covered():
    """PSA は 再仕入れの入力 / CSV監査くん / check_csv の3か所で見る。"""
    for rel, need in (
            (("iMakHQ", "tools", "psa_restock_build.py"), "_cost_sanity"),
            (("iMakHQ", "tools", "csv_auditor.py"), "cost_sanity_exclusions"),
            (("iMakTCG", "check_csv.py"), "cost_issues")):
        s = _io.open(os.path.join(_ROOT, *rel), encoding="utf-8").read()
        assert need in s, rel[-1]
