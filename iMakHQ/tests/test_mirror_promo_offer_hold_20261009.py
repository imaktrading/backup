# -*- coding: utf-8 -*-
"""オファーが来ている・承諾して支払い待ちのミラーには、夜の処理で広告を付け直さない (2026-10-09)。"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
import mirror_promo_bestoffer as M

NOW = dt.datetime(2026, 10, 9, 1, 0, tzinfo=dt.timezone.utc)


def _x(status, exp="2026-10-09T19:48:39.000Z"):
    return f"<BestOffer><ExpirationTime>{exp}</ExpirationTime><Status>{status}</Status></BestOffer>"


def test_active_offer_is_held():
    assert M.offer_hold(_x("Active"), NOW)


def test_recently_accepted_offer_is_held():
    assert M.offer_hold(_x("Accepted", "2026-10-08T13:51:26.000Z"), NOW)


def test_old_accepted_or_declined_is_not_held():
    assert not M.offer_hold(_x("Accepted", "2026-09-20T00:00:00.000Z"), NOW)
    assert not M.offer_hold(_x("Declined"), NOW)
    assert not M.offer_hold("", NOW)


class _Tok:
    def get(self):
        return "t"


class _Fx:
    def __init__(self, held_ids):
        self.held = held_ids

    def post(self, call, body, tok, site=None):
        return _x("Active") if any(i in body for i in self.held) else ""


def test_drop_offer_holds_removes_only_held():
    todo = {k: {"promo": []} for k in M.SITES}
    todo["au"]["promo"] = ["820133853296", "111"]
    assert M.drop_offer_holds(_Fx({"820133853296"}), _Tok(), todo, now=NOW) == 1
    assert todo["au"]["promo"] == ["111"]
