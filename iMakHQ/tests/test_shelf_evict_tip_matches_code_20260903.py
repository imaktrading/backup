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
    # ★2026-09-06 ユーザー確定で基準が変わった: **出品30日で取り下げる** (G-shock も30日)。
    #   落とす順は ウォッチ少ない順 → 表示少ない順 → 金額 大きい順。
    #   理由: 当店は月間回転率 0.8% まで落ちており、表示やCTRが低いのは
    #   **店の順位が下がった結果**の可能性が高い。その自店データから日数を
    #   決めると悪循環を固定する。詳細は test_shelf_rotate_30days_20260906.py。
    # ① は今も 空く額の降順。② はウォッチ→表示→金額。
    assert re.search(r"rank = \(0, 0, -shelf_of\(r\)\)", src), "①が空く額の降順でない"
    assert '_f(r.get("watch")),' in src, "②がウォッチ順でない"


def test_gshock_is_dropped_at_30_days_too():
    """★2026-09-06 ユーザー確定で **G-shock も30日**になった。

    2026-09-02 は「G-SHOCK は中央値284日で売れるので30日で落とすと売れる在庫を捨てる」
    としていたが、その根拠は **月間回転率 0.8% まで落ちた自店データ** だった。
    店の順位が下がっている状態の数字なので、そこから日数を決めると悪循環を固定する。
    実際、取下げを始めてからオファーが増えており、棚を減らす方向が効いている。
    → 予測をやめて **30日で回す**。効果は月間回転率で測る。
    """
    assert SE.STALE_MAX_AGE["G-shock"] == SE.STALE_MAX_AGE["TCG"] == 30
