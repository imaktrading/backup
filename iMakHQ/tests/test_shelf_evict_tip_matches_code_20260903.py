# -*- coding: utf-8 -*-
"""棚のボタン説明が実装とずれていないか (2026-09-03)。

## 実害
9/2 に END ルールを実測から決め直した (`d53e9d9`) のに、パネルのヒント文だけ古いままで
**3か所が嘘**になっていた:

    「アクセスの少ない順」      → 実際は 空く額の大きい順
    「TCG/G-SHOCK の30日超」    → G-SHOCK は 365日
    「30日未満は触りません」    → G-SHOCK は 365日未満

ヒントは押す前に読む唯一の説明なので、ここがずれていると **取り返しのつかない End を
誤った理解で押す**ことになる。文と実装を機械で結び付けて、次にルールを変えた時は
テストが落ちるようにする。
"""
import os
import re
import sys

_HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TOOLS = os.path.join(_HQ, "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import shelf_evict as SE  # noqa: E402


def _tip():
    src = open(os.path.join(_HQ, "control_panel.py"), encoding="utf-8").read()
    # ★2026-09-03: ボタンを①②に分けたので、日数の説明は② (在庫ありを落とす) に移った
    i = src.index('"label": "📉 棚② ')
    seg = src[i:i + 2500]
    j = seg.index('"tip":')
    return seg[j:seg.index('",\n', j)]


def test_tip_states_every_age_limit_actually_used():
    """カテゴリごとの期限が全部ヒントに書いてあること。"""
    tip = _tip()
    for cat, days in SE.STALE_MAX_AGE.items():
        assert str(days) in tip, f"{cat}={days}日 がヒントに無い"


def test_tip_does_not_claim_access_order():
    """アクセス順という古い説明を残さない (並びは空く額の大きい順)。"""
    assert "アクセスの少ない順" not in _tip()


def test_code_really_sorts_by_freed_amount():
    """ヒントの根拠。並びが空く額の降順であること。"""
    src = open(os.path.join(_TOOLS, "shelf_evict.py"), encoding="utf-8").read()
    assert re.search(r"rank\s*=\s*-shelf_of\(r\)", src), "空く額の降順で並べていない"


def test_gshock_is_not_dropped_at_30_days():
    """G-SHOCK は中央値284日で売れる。30日で落とすと売れる在庫を捨てる。"""
    assert SE.STALE_MAX_AGE["G-shock"] > SE.STALE_MAX_AGE["TCG"]
    assert SE.STALE_MAX_AGE["G-shock"] == 365
