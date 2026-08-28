# -*- coding: utf-8 -*-
"""棚割の①(数量0)を live 一覧から出す (2026-08-28)。

ユーザー指摘「手動で毎回最新をDLする方が非効率でしょ」。
①(数量0) は毎回取り直している live 一覧から直接わかるので、Seller Hub の
レポート/ファネルを待つ必要がない。レポートが要るのは②(表示回数の少ない順)の並び順だけ。

実害 (2026-08-28): 5日前のレポートで、**在庫が戻った出品**(G-Shock GMW-B5000-1)を
落とす候補に挙げていた。live から出せば起きない。
"""
from __future__ import annotations

import datetime
import os
import sys

HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HQ, "tools"))

import shelf_evict as E                                           # noqa: E402

NOW = datetime.datetime(2026, 8, 28)
KEY = lambda t: (t or "").strip().lower()                         # noqa: E731

LIVE = {
    # 数量0 の US 出品 = 棚を空ける対象
    "820000000001": {"cur": "USD", "avail": 0, "usd": 100.0, "title": "Card A",
                     "start": "2026-06-01T00:00:00.000Z"},
    # 在庫が戻っている = 対象外
    "820000000002": {"cur": "USD", "avail": 1, "usd": 200.0, "title": "Watch B",
                     "start": "2026-06-01T00:00:00.000Z"},
    # ミラー (非USD) = 行にはしないが、親の棚額に足す
    "358000000001": {"cur": "CAD", "avail": 0, "usd": 30.0, "title": "Card A",
                     "start": "2026-06-01T00:00:00.000Z"},
}


class TestLiveRows:
    def test_数量0のUS出品だけ行にする(self):
        rows = E.rows_from_live(LIVE, set(), KEY, now=NOW)
        assert [r["item_id"] for r in rows] == ["820000000001"]

    def test_在庫が戻っている出品は落とさない(self):
        # 5日前のレポートで実際に起きた誤選定を防ぐ
        rows = E.rows_from_live(LIVE, set(), KEY, now=NOW)
        assert all(r["item_id"] != "820000000002" for r in rows)

    def test_棚額はミラー込み(self):
        rows = E.rows_from_live(LIVE, set(), KEY, now=NOW)
        assert rows[0]["price"] == 100.0 and rows[0]["_mirror"] == 30.0

    def test_既に落とした分は出さない(self):
        assert E.rows_from_live(LIVE, {"820000000001"}, KEY, now=NOW) == []

    def test_出品日から経過日数を出す(self):
        rows = E.rows_from_live(LIVE, set(), KEY, now=NOW)
        assert rows[0]["age_days"] == 88


class TestAgeDays:
    def test_読めない値は0(self):
        assert E.age_days_of("") == 0
        assert E.age_days_of("not-a-date") == 0

    def test_未来日は0(self):
        assert E.age_days_of("2026-09-01T00:00:00.000Z", now=NOW) == 0


class TestTierStillHolds:
    def test_数量0は全カテゴリが対象(self):
        assert E.tier_of({"qty": 0}, category="Tシャツ") == E.TIER_OOS

    def test_売れた実績があるものは触らない(self):
        assert E.tier_of({"qty": 1, "sold_qty": 1, "age_days": 99}) is None


class TestApparelIsNeverEvicted:
    """アパレルは落とさない (2026-08-28 ユーザー確定)。

    公式在庫が戻れば監視くんが**数量を戻す**。出品が生きていれば復活できるが、
    取り下げると戻せない (出し直しになる)。数量0 でも触らない。
    """

    def test_UNIQLO_GU_は候補にしない(self):
        live = {"820000000009": {"cur": "USD", "avail": 0, "usd": 30.0,
                                 "title": "UNIQLO UT Pokemon 30th Anniversary Tee",
                                 "start": "2026-06-01T00:00:00.000Z"}}
        assert E.rows_from_live(live, set(), KEY, now=NOW) == []

    def test_銘柄を問わず衣類を守る(self):
        # UNIQLO/GU 以外の T シャツも同じ性質 (公式在庫が戻る)
        assert E.is_protected("Dragon Ball DAIMA Goku T-Shirt, 3XL, Black, Anime Graphic")
        assert E.is_protected("GU Hiromichi Yokochi Sukajan Dragon T-Shirt")

    def test_カードや時計は守らない(self):
        assert not E.is_protected("PSA 10 Pokemon Japanese Sv9 #105 Lillie's Ribombee")
        assert not E.is_protected("CASIO G-Shock GA-010GGB-1A9 Mens Watch")
