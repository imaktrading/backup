# -*- coding: utf-8 -*-
"""取下再出品② — gshock_to_csv --relist モードの行選択ロジック。

2026-06-06: B空欄キュー(61件)を無視し保留リストの指定URLだけ即live再出品する
--relist モードを追加。価格/タイトル/item specifics は管理スプシの実コストから
最新ロジックで再生成する(据置しない)。本テストはその純粋行選択 _select_gshock_row
と即liveスケジュールを検証 (network無し)。
"""
import importlib.util
import os

import pytest

_GSHOCK = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "iMakG-shock", "gshock_to_csv.py"))


@pytest.fixture(scope="module")
def g():
    spec = importlib.util.spec_from_file_location("gshock_to_csv_relist", _GSHOCK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _row(url="", item_id="", title_jp="", sold="", cost_n="", desc="", title_en="", cat="G-shock"):
    """スプシ行を列位置で組む。A0 url / B1 itemid / C2 title_jp / D3 sold / ... H7 desc / I8 title_en
    / N13 実コスト / R17 category。pick_cost_jpy は N列(13)優先。"""
    r = [""] * 18
    r[0], r[1], r[2], r[3], r[7], r[8], r[13], r[17] = url, item_id, title_jp, sold, desc, title_en, cost_n, cat
    return r


def test_relist_only_urls_ignores_filled_b(g):
    # 取下再出品②: 指定URLは B(itemID)埋まり・売切れでも採用 (取下げ済を再出品)
    row = _row(url="https://www.amazon.co.jp/dp/B0DDS4Z29W", item_id="357370826397",
               title_en="CASIO G-SHOCK GM-2110D-2AJF Metal", cost_n="43500")
    target, reason = g._select_gshock_row(row, only_urls={"https://www.amazon.co.jp/dp/B0DDS4Z29W"})
    assert reason is None
    url, model, cost = target
    assert model == "GM-2110D-2AJF"
    assert str(cost).replace("¥", "").replace(",", "") == "43500"  # スプシ実コスト → 最新pricingが再算出


def test_relist_only_urls_excludes_other(g):
    row = _row(url="https://www.amazon.co.jp/dp/OTHER00000", title_en="CASIO G-SHOCK GA-2100-1A1", cost_n="20000")
    target, reason = g._select_gshock_row(row, only_urls={"https://www.amazon.co.jp/dp/B0DDS4Z29W"})
    assert target is None and reason == 'not_target'


def test_normal_mode_requires_b_empty(g):
    # 通常モード(only_urls=None): B埋まり = 出品済 → 除外
    filled = _row(url="u1", item_id="123", title_en="CASIO G-SHOCK GA-2100-1A1", cost_n="20000")
    assert g._select_gshock_row(filled, only_urls=None)[1] == 'not_target'
    empty = _row(url="u2", item_id="", title_en="CASIO G-SHOCK GA-2100-1A1", cost_n="20000")
    target, reason = g._select_gshock_row(empty, only_urls=None)
    assert reason is None and target[1] == "GA-2100-1A1"


def test_partial_and_no_model_skipped(g):
    no_model = _row(url="u3", title_en="CASIO watch no model", cost_n="10000")
    assert g._select_gshock_row(no_model, only_urls={"u3"})[1] == 'no_model'


def test_immediate_schedule_flag(g):
    g._IMMEDIATE_SCHEDULE = True
    try:
        imm = g.get_schedule_time()
        g._IMMEDIATE_SCHEDULE = False
        future = g.get_schedule_time()
    finally:
        g._IMMEDIATE_SCHEDULE = False
    assert imm < future   # 即live(現在) < 通常(2週間後)
