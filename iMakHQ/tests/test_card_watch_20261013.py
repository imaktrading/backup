# -*- coding: utf-8 -*-
"""売れたカードの仕入元の見張り (card_watch・2026-10-13)。"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import card_watch as C  # noqa: E402

W = {"need_any": ["CLASSIC", "CLK", "013/032", "クラシック"], "ng": ["連番", "セット", "まとめ", "ラッキー"]}


def test_matches_the_card():
    assert C.matches("【PSA10】バリヤード ポケモンカードClassic CLK 013/032", W)
    assert C.matches("2023 POKEMON CLK JP MR. MIME 013 PSA10", W)
    assert C.matches("PSA10 バリヤード　クラシック", W)


def test_skips_other_grades_lots_and_other_cards():
    assert not C.matches("バリヤード　Classic 013 CLK 【PSA9】", W)
    assert not C.matches("【PSA10 連番】バリヤード　Classic 013 CLK", W)
    assert not C.matches("PSA10 フシギソウ ラッキー バリヤード Classic", W)
    assert not C.matches("PSA10 バリヤード AR SV2a 179/165", W)
    assert not C.matches("状態A バリヤード 013/032 CLK クラシック", W)       # 鑑定なし


def test_active_and_new_hits():
    t = dt.date(2026, 10, 13)
    ws = [{"until": "2026-10-21"}, {"until": "2026-10-12"}, {"until": "2026-10-30", "done": True}]
    assert C.active(ws, t) == [ws[0]]
    assert C.new_hits([{"id": "m1"}, {"id": "m2"}], ["m1"]) == [{"id": "m2"}]
