# -*- coding: utf-8 -*-
"""ファネル: 生レポートの世代アーカイブ 回帰テスト (2026-07-24)。

ユーザー方針「DLした生CSVを貯めれば いつでも分析レポートを作れる」= 派生分類でなく
生データを世代ごとに永久保管 → 後から任意のトレンド分析を遡って作れる。
archive_generation が active レポートの内容日付フォルダに冪等コピーすることを固定。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import listing_funnel as lf  # noqa: E402


def _touch(p, body="x"):
    with open(p, "w", encoding="utf-8") as f:
        f.write(body)


def test_archives_into_content_date_folder(tmp_path):
    d = str(tmp_path)
    active = os.path.join(d, "eBay-all-active-listings-report-2026-07-23-999.csv")
    unsold = os.path.join(d, "eBay-unsold-listings-report-2026-07-23-888.csv")
    _touch(active); _touch(unsold)
    adir, n = lf.archive_generation(d, [active, unsold, None])
    assert os.path.basename(adir) == "20260723"     # 内容日付フォルダ
    assert n == 2
    assert os.path.isfile(os.path.join(adir, os.path.basename(active)))
    # 直下の元ファイルは残す(funnel が読むため)
    assert os.path.isfile(active)


def test_idempotent_no_recopy(tmp_path):
    d = str(tmp_path)
    active = os.path.join(d, "eBay-all-active-listings-report-2026-07-23-1.csv")
    _touch(active)
    lf.archive_generation(d, [active])
    adir, n = lf.archive_generation(d, [active])   # 2回目
    assert n == 0                                   # 既存はコピーしない(冪等)


def test_no_date_no_archive(tmp_path):
    """active の内容日付が取れなければ archive しない(誤フォルダ名を作らない=fail-closed)。"""
    d = str(tmp_path)
    active = os.path.join(d, "eBay-all-active-listings-report-nodate.csv")
    _touch(active)
    adir, n = lf.archive_generation(d, [active])
    assert adir is None and n == 0
