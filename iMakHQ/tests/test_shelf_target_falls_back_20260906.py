# -*- coding: utf-8 -*-
"""金額指定なしの既定を「前回の出品額ぶん」にする (2026-09-06 ユーザー確定).

> 金額指定なしなら「前回の出品額ぶん」にして

それまでは「**その日**の出品額」だった。出品していない日は $0 になり、
押しても1件も落ちなかった (2026-09-06 18:08 の実走行で "今日はまだ出品して
いないので、落とす分もありません" と出て終了)。

棚は出品していない日でも回したいので、**直近で出品した日の額**にさかのぼる。
その日に出していれば その額 = 従来と同じ動き。
"""
from __future__ import annotations

import io
import os
import sys
import datetime as dt

_TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import shelf_evict as E  # noqa: E402


def _csv(d, stamp, name, prices):
    p = os.path.join(str(d), "%s_upload_%s_1.csv" % (name, stamp))
    with io.open(p, "w", encoding="utf-8-sig", newline="") as f:
        f.write("*StartPrice\n")
        for v in prices:
            f.write("%s\n" % v)
    return p


class TestFallback:
    def test_uses_today_when_listed_today(self, tmp_path):
        _csv(tmp_path, "20260906", "psa", [100, 200])
        _csv(tmp_path, "20260901", "psa", [999])
        got = E.listed_today_amount(str(tmp_path), dt.date(2026, 9, 6))
        assert got == 300, "その日に出していれば その日の額"

    def test_falls_back_to_the_last_listing_day(self, tmp_path):
        """★本丸。今日 出していなければ、直近で出した日の額を使う。"""
        _csv(tmp_path, "20260904", "psa", [100, 50])
        _csv(tmp_path, "20260901", "psa", [999])
        got = E.listed_today_amount(str(tmp_path), dt.date(2026, 9, 6))
        assert got == 150, "直近(9/4)の額でなく %s になった" % got

    def test_skips_days_with_zero(self, tmp_path):
        """金額0の日は「出品した日」と見なさない (遡り続ける)。"""
        _csv(tmp_path, "20260905", "psa", [])
        _csv(tmp_path, "20260903", "psa", [77])
        got = E.listed_today_amount(str(tmp_path), dt.date(2026, 9, 6))
        assert got == 77

    def test_no_csv_at_all_is_zero(self, tmp_path):
        """1枚も無ければ 0。無いものを勝手に作らない。"""
        assert E.listed_today_amount(str(tmp_path), dt.date(2026, 9, 6)) == 0.0

    def test_ignores_backup_files(self, tmp_path):
        _csv(tmp_path, "20260904", "psa", [100])
        io.open(os.path.join(str(tmp_path), "psa_upload_20260905_1.csv.bak"),
                "w", encoding="utf-8").write("*StartPrice\n9999\n")
        assert E.listed_today_amount(str(tmp_path), dt.date(2026, 9, 6)) == 100


class TestUploadDays:
    def test_newest_first(self, tmp_path):
        for stamp in ("20260901", "20260906", "20260904"):
            _csv(tmp_path, stamp, "psa", [1])
        assert E.upload_days(str(tmp_path)) == ["20260906", "20260904", "20260901"]

    def test_empty_dir(self, tmp_path):
        assert E.upload_days(str(tmp_path)) == []
