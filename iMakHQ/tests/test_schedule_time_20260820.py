# -*- coding: utf-8 -*-
"""予約出品 — CSV の ScheduleTime を eBay に渡す (2026-08-20 新設).

★実害: CSV には 2週間後の ScheduleTime を書いていたのに、`build_item_xml` を
  引数なしで呼んでいたため **eBay には一度も送っていなかった**。
  「予約で出す」つもりの操作が全部その場で公開されていた。

既定は今のまま (即時公開)。`--schedule` を付けた時だけ渡す。PSA など既存フローの
挙動を勝手に変えないため。
"""
from __future__ import annotations

import os
import sys

HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HQ, "tools"))

import ebay_upload_csv as U                                      # noqa: E402

ROW = {"*Title": "t", "*Category": "69528", "*StartPrice": "10",
       "CustomLabel": "sku", "ScheduleTime": "2026-09-03 09:27:52"}


class TestScheduleTimeOf:
    def test_csv_format_becomes_gmt(self):
        assert U.schedule_time_of(ROW) == "2026-09-03T09:27:52Z"

    def test_slashes_are_accepted(self):
        assert U.schedule_time_of({"ScheduleTime": "2026/09/03 09:27:52"}) \
            == "2026-09-03T09:27:52Z"

    def test_already_gmt_is_left_alone(self):
        assert U.schedule_time_of({"ScheduleTime": "2026-09-03T09:27:52Z"}) \
            == "2026-09-03T09:27:52Z"

    def test_empty_stays_empty(self):
        """空 = 即時公開。無い物を作らない."""
        assert U.schedule_time_of({}) == ""
        assert U.schedule_time_of({"ScheduleTime": "  "}) == ""


class TestItemXml:
    def test_schedule_reaches_the_xml(self):
        x = U.build_item_xml(ROW, U.schedule_time_of(ROW))
        assert "<ScheduleTime>2026-09-03T09:27:52Z</ScheduleTime>" in x

    def test_default_is_still_immediate(self):
        """★既定を変えない。PSA は今までどおり即時に出る."""
        assert "ScheduleTime" not in U.build_item_xml(ROW)


class TestOptIn:
    def test_the_flag_exists_and_is_opt_in(self):
        import inspect
        src = inspect.getsource(U)
        assert '"--schedule"' in src and 'action="store_true"' in src
        assert "schedule_time_of(row) if a.schedule else \"\"" in src


class TestBestOffer:
    """★CSV の `BestOfferEnabled` を eBay に送っていなかった (2026-08-21).

    ScheduleTime / Product:EAN と同じ型で、**CSV に書いてあるのに写していなかった**。
    ベストオファーが付かないまま出ていたので、オファー対応の導線が死んでいた。
    """

    def test_csvで1なら送る(self):
        x = U.build_item_xml({"*Title": "t", "BestOfferEnabled": "1"})
        assert "<BestOfferDetails><BestOfferEnabled>true</BestOfferEnabled>" in x

    def test_指定が無ければ送らない(self):
        assert "BestOffer" not in U.build_item_xml({"*Title": "t"})

    def test_ゼロなら送らない(self):
        assert "BestOffer" not in U.build_item_xml({"*Title": "t", "BestOfferEnabled": "0"})
