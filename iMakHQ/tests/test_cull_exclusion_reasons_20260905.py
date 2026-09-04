# -*- coding: utf-8 -*-
"""CULL の除外理由が嘘だった件 (2026-09-05)。

9/5 の走行ログ:
    CULL(在庫切れ&需要皆無) = 161件
    ※ age<1日 / age不明 / $0未満 で対象外 = 150件

実際の150件は 既落とし77 + アパレル保護76 で、**年齢や価格で外れた行は0件**だった
(161件は全部 US・全部 age>=3日)。表示が `len(cull) - len(eligible)` の引き算に
理由を後付けしていたのが原因。判定 (select) と集計を reject_reason() 1本に通し、
理由は数えた実数だけを出す。
"""
import os
import sys

_TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import cull_end as C  # noqa: E402


def _row(iid, title="PSA 10 Pokemon Charizard", age=100, price=200.0,
         flags="CULL", site="US"):
    return {"item_id": iid, "title": title, "price": price,
            "age_days": age, "flags": flags, "site": site}


def test_already_ended_is_not_blamed_on_age_or_price():
    """既に落とした行を「age不明/$未満」と説明しない (9/5 の実害そのもの)。"""
    r = _row("a", age=100, price=200.0)
    why = C.reject_reason(r, done={"a"})
    assert why == "既に落とした", why


def test_apparel_is_not_blamed_on_age_or_price():
    r = _row("b", title="UNIQLO UT One Piece Luffy T-Shirt", age=100, price=200.0)
    why = C.reject_reason(r, done=set())
    assert why is not None and "アパレル" in why, why


def test_reasons_partition_the_cull_rows():
    """理由別の合計 + 残った候補 == CULL 件数。引き算で辻褄を合わせない。"""
    rows = [
        _row("keep"),                                              # 対象
        _row("done"),                                              # 既に落とした
        _row("ut", title="GU Graphic Tee Sanrio T-Shirt"),         # アパレル
        _row("mirror", site="UK"),                                 # US以外
        _row("young", age=0),                                      # age不明
        _row("nocull", flags="RESTOCK"),                           # そもそも CULL でない
    ]
    done = {"done"}
    cull, eligible, _picked = C.select(rows, done_ids=done)
    rejected = [C.reject_reason(r, done) for r in cull]
    assert len(cull) == 5, cull
    assert sum(1 for w in rejected if w) + len(eligible) == len(cull)
    assert {r["item_id"] for r in eligible} == {"keep"}


def test_select_agrees_with_reject_reason():
    """select() が独自にフィルタを書き直していない (二重管理の再発防止)。"""
    rows = [_row("a"), _row("b", site="AU"), _row("c", age=0),
            _row("d", title="UNIQLO UT Dragon Ball T-Shirt"), _row("e")]
    done = {"e"}
    cull, eligible, _ = C.select(rows, done_ids=done)
    for r in cull:
        in_eligible = any(x["item_id"] == r["item_id"] for x in eligible)
        assert in_eligible == (C.reject_reason(r, done) is None), r["item_id"]
