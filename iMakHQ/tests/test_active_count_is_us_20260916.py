# -*- coding: utf-8 -*-
"""画面の「出品中」は US の実数 (2026-09-16 ユーザー指摘「出品中 585 これって違うよね？」)。

それまでは Browse API を q="Japan" で検索した件数を出していた。タイトルに Japan が入らない
出品 (G-SHOCK / モンベル / ガチャ 等) が丸ごと抜け、**US 実数 1,027件 に対し 585** と出ていた。
ミラー (UK/AU/CA/DE = 3,741件との差) は自分で増減させる物ではないので数えない (ユーザー選択)。
"""
import os
import sys

HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HQ, "tools"))

import funnel_io as F  # noqa: E402

PANEL = open(os.path.join(HQ, "control_panel.py"), encoding="utf-8").read()

ROWS = [{"Item number": "1", "Listing site": "US"},
        {"Item number": "2", "Listing site": "UK"},
        {"Item number": "3", "Listing site": "Australia"},
        {"Item number": "4", "Listing site": "US"},
        {"Item number": "", "Listing site": "US"},
        {"Item number": "5", "Listing site": ""}]


def test_us_only_from_snapshot():
    assert F.us_active_from_snapshot_rows(ROWS) == {"1", "4"}
    assert F.non_us_from_snapshot_rows(ROWS) == {"2", "3"}      # ミラーは別に数えられる


def test_panel_uses_the_snapshot_not_the_keyword_search():
    assert "_funnel_io().us_active_count()" in PANEL
    i = PANEL.index('"total_active": us_n if us_n is not None else total_active')
    assert i > 0                                                # 取れない時だけ従来値に落ちる
    assert '"active_is_us"' in PANEL                            # US だけと画面で分かるようにする


def test_count_matches_the_snapshot_file():
    """実データ: スナップショットの US 行数と一致する。"""
    n, at = F.us_active_count()
    if n is None:
        return                                                  # スナップショットが無い環境では見ない
    rows = []
    import csv, io as _io
    with _io.open(F.latest_snapshot_path(), encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    assert n == len(F.us_active_from_snapshot_rows(rows)) and at
