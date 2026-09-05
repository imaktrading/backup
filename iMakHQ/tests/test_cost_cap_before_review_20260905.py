# -*- coding: utf-8 -*-
"""仕入値が上限超えの行を、目視の後で捨てていた件 (2026-09-05)。

9/5 の走行: 目視した16件のうち2件が、その後の監査で
「仕入値が上限を超えている ¥72,999 / ¥75,000 (上限 ¥70,000)」で落とされた。
落とされた行は未出品のまま残るので、翌日また拾われ、また目視に出る。

仕入値は **枠を選ぶ時点で既に分かっている** (cost_map) ので、
そこで落とせば人に見せずに済む。既にある前置き
(GAP / OUT-OF-SCOPE / NO-IMAGE / LIVE-DUP) と同じ場所に置く。
"""
import io
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_API = os.path.join(_ROOT, "iMakeBayAPI")
if _API not in sys.path:
    sys.path.insert(0, _API)

import pricing_engine as PE  # noqa: E402

_SRC = io.open(os.path.join(_ROOT, "iMakTCG", "psa_to_csv.py"), encoding="utf-8").read()


def test_cost_cap_is_checked_before_the_batch_is_chosen():
    """前置きに COST-CAP がある = 目視の前に落ちる。"""
    assert '_drop["COST-CAP"] = _hi' in _SRC
    assert "仕入値が上限を超えている(目視しても最後に落ちる)" in _SRC
    # 枠を選ぶ前の一覧に出る (黙って落とさない)
    i = _SRC.index('_drop["COST-CAP"]')
    j = _SRC.index('print(f"  ⏭️ 枠を選ぶ前に除外')
    assert i < j, "COST-CAP の判定が一覧の出力より後ろにある"


def test_only_the_cap_is_pre_filtered_not_every_cost_problem():
    """「安すぎる」「ダミー数字」まで前で落とさない。

    上限超えは値が変わらない限り永久に落ちるので前で切ってよいが、
    他の理由は取得失敗が原因のことがあり、前で切ると救えなくなる。
    """
    i = _SRC.index("_why = _pe.cost_sanity(cost_map.get(_c))")
    assert '"上限" in _why' in _SRC[i:i + 200]


def test_cost_sanity_still_flags_the_two_real_cases():
    """9/5 に落ちた実際の2件が上限判定に当たる (上限 ¥70,000)。"""
    for jpy in (72999, 75000):
        why = PE.cost_sanity(jpy)
        assert why and "上限" in why, (jpy, why)
    assert PE.cost_sanity(69000) is None


def test_missing_cost_is_not_treated_as_over_the_cap():
    """仕入値が無い行をここで落とさない (別の経路で fail-closed する)。"""
    assert PE.cost_sanity(None) is None
