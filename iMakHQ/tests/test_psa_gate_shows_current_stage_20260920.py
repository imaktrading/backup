# -*- coding: utf-8 -*-
"""PSA 再仕入れ① は「今出る段」の件数だけ出す (2026-09-20)。

ユーザー「4件と表示されているけど、押すと1件しか出てこない」。
このボタンは2段あり、①変種の目視ゲート に答えてから ②仕入元の照合 に進む。
2つを足していたので、1段目が残っている間は 4件 と出て画面には1件しか出なかった
(実測 2026-09-20 19:53 の走行ログ: 「新規/未解決 1件のみ目視」でブラウザを開いて停止。
count_workload は variant_todo=1 / actionable=3)。
"""
from __future__ import annotations

import os
import sys

HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HQ, "console"))

import server as S  # noqa: E402


def _gate(**kw):
    return S.summarize({"psa_gate": kw}).get("psa_gate") or {}


def test_変種の目視が残っている間はその件数だけ():
    g = _gate(variant_todo=1, actionable=3)
    assert g["n"] == 1, g
    assert "3件" in (g.get("note") or ""), g       # 次の段は note で伝える


def test_変種が片付いたら照合の件数になる():
    assert _gate(variant_todo=0, actionable=3)["n"] == 3


def test_どちらも無ければ0():
    g = _gate(variant_todo=0, actionable=0)
    assert g["n"] == 0 and g["state"] != "todo"
