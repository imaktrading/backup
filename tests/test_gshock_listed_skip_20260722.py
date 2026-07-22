# -*- coding: utf-8 -*-
"""G-shock 抽出時の「既出品(同型番 live)の2枚目除外」回帰テスト (2026-07-22)。

背景: 同型番が live 出品済でも 2枚目行(B空)が毎回 抽出→生成→dedupe除外 を繰り返し、
1回10枠のうち数枠を空振りで浪費していた(2026-07-22 run で 3/10 枠: GWX-5700CS-1JF 等)。
PSA の既出品KEY除外と同思想で、抽出段階で出品中型番と突合して先に止める。
KEY書き戻しでなく動的判定 = live が売れて消えれば2枚目は自動で再浮上(解除操作不要)。
"""
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "iMakG-shock")))
from gshock_to_csv import _select_gshock_row, _listed_gshock_models  # noqa: E402


def _row(url="https://amazon.co.jp/dp/B0TEST", item_id="", title="G-SHOCK GA-2100-1A1JF 腕時計",
         sold="", key=""):
    r = [""] * 35
    r[0] = url
    r[1] = item_id
    r[2] = title
    r[3] = sold
    r[17] = "G-shock"
    r[34] = key
    return r


def test_listed_models_collects_live_only():
    """出品中(B有+売切空)の型番だけ集合に入る。AI列KEY と タイトル抽出の両方。"""
    vals = [["header"] * 35,
            _row(item_id="123", title="G-SHOCK GWX-5700CS-1JF", key="GWX-5700CS-1JF"),   # live
            _row(item_id="456", title="G-SHOCK GA-110GB-1AJF", sold="○"),                 # 売切=対象外
            _row(item_id="", title="G-SHOCK DW-5600UE-1JF")]                              # 未出品=対象外
    listed = _listed_gshock_models(vals)
    assert "GWX-5700CS-1JF" in listed
    assert "GA-110GB-1AJF" not in listed      # 売切は live でない
    assert "DW-5600UE-1JF" not in listed      # 未出品は live でない


def test_second_copy_of_live_model_skipped():
    """★本命: live 出品済と同型番の2枚目行(B空)は 'already_listed' で抽出しない。"""
    listed = {"GWX-5700CS-1JF"}
    target, reason = _select_gshock_row(_row(title="G-SHOCK GWX-5700CS-1JF 新品"),
                                        listed_models=listed)
    assert target is None and reason == "already_listed"


def test_unlisted_model_still_extracted():
    """live に無い型番は従来どおり抽出される。"""
    listed = {"GWX-5700CS-1JF"}
    target, reason = _select_gshock_row(_row(title="G-SHOCK GA-2100-1A1JF 新品"),
                                        listed_models=listed)
    assert target is not None and reason is None
    assert target[1] == "GA-2100-1A1JF"


def test_relist_mode_ignores_listed_filter():
    """取下再出品(only_urls)は明示指定なので、live 同型番でも通す。"""
    url = "https://amazon.co.jp/dp/B0RELIST"
    listed = {"GWX-5700CS-1JF"}
    target, reason = _select_gshock_row(
        _row(url=url, item_id="999", title="G-SHOCK GWX-5700CS-1JF"),
        only_urls={url}, listed_models=listed)
    assert target is not None, "取下再出品まで塞いではいけない"


def test_no_listed_set_behaves_as_before():
    """listed_models 未指定(None)なら従来挙動(後方互換)。"""
    target, reason = _select_gshock_row(_row(title="G-SHOCK GWX-5700CS-1JF"))
    assert target is not None and reason is None
