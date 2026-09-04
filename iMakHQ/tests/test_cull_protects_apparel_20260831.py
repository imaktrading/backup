# -*- coding: utf-8 -*-
"""CULL がアパレルを守っていなかった穴 (2026-08-31)。

MIN_PRICE ($100) を撤廃した実測で、eligible 153件中92件 (6割) が UNIQLO の
T-Shirt だと判明した。安いUT系Tシャツの多くが $100 未満で **偶然** 弾かれていた
だけで、cull_end.py 自体はアパレルを守っていなかった。

shelf_evict.py は 2026-08-28 に同じ理由 (公式在庫が戻れば監視くんが数量を戻す。
取り下げると戻せない) でアパレルを PROTECTED_TITLE として守っている。
cull_end.py にも同じ保護を入れ、判定は shelf_evict.is_protected に一本化する
(2か所に書くと片方が腐る)。
"""
import os
import sys

_TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import cull_end as C  # noqa: E402
import shelf_evict as SE  # noqa: E402


def _row(iid, title, age=100, price=50.0, flags="CULL", site="US"):
    return {"item_id": iid, "title": title, "price": price,
            "age_days": age, "flags": flags, "site": site}


def test_select_excludes_apparel():
    rows = [
        _row("a", "UNIQLO UT Dragon Ball Frieza T-Shirt Japan", price=90.98),
        _row("b", "CASIO G-Shock GA-2100 Mens Watch", price=90.0),
    ]
    _cull, eligible, _picked = C.select(rows)
    ids = {r["item_id"] for r in eligible}
    assert ids == {"b"}, "アパレルを落とそうとしている"


def test_end_status_explains_apparel_protection():
    r = _row("a", "UNIQLO UT One Piece Luffy T-Shirt")
    status = C.end_status(r, done_ids=set())
    assert "アパレル" in status


def test_protection_logic_is_not_duplicated():
    """判定は shelf_evict.is_protected に一本化する (二重管理で片方が腐るのを防ぐ)。

    ★2026-09-05: 除外判定を select() から reject_reason() に移した
    (画面表示と判定が食い違っていたため)。見る先を移しただけで意図は同じ。
    """
    import inspect
    src = inspect.getsource(C.reject_reason)
    assert "from shelf_evict import is_protected" in src
    assert "PROTECTED_TITLE" not in src, "cull_end 側に正規表現を複製している"
    # select() は自前でフィルタを書き直さず reject_reason だけを見る
    assert "reject_reason" in inspect.getsource(C.select)


def test_cull_and_shelf_evict_agree_on_what_is_protected():
    """2つのボタンで判定が食い違わない (同じ関数を呼んでいるので必ず一致する)。"""
    titles = ["UNIQLO UT Test Tee", "CASIO G-Shock Test", "PORTER Tanker Bag",
             "Dragon Ball DAIMA Hoodie"]
    for t in titles:
        assert SE.is_protected(t) == (C.end_status(
            _row("x", t), done_ids=set()) == "🗑 取下げ 未 (アパレル = 監視くんが公式在庫を見て自動復活)")
