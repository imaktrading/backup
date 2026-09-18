"""補URL の「補充」と「入れ替え」は別の流れ (2026-09-19)。

ユーザー「今日やることに PSA入れ替え③ が出てきてないけど / 実際押して作業している」。
同じ ③ として1本の順番に入れていたため、補充が0件になるまで入れ替えが隠れていた
(実測: 補充88件 / 入れ替え17件)。
"""
import os

HQ = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
APP = open(os.path.join(HQ, "console", "static", "app.js"), encoding="utf-8").read()


def test_入れ替えは別の流れとして数える():
    body = APP.split("function chainOf(j) {")[1].split("function rankOf")[0]
    assert '/入れ替え/.test(j.label) ? "/swap" : ""' in body


def test_入れ替えを順番の後ろに下げない():
    body = APP.split("function rankOf(j) {")[1].split("function firstStepOnly")[0]
    assert "0.5" not in body        # 補充のあと、にしない (別の流れなので競合しない)


def test_順番待ちの仕組み自体は残す():
    """①→②→③ の順番待ちは今までどおり (ユーザーは廃止を指示していない)。"""
    assert "firstStepOnly" in APP
