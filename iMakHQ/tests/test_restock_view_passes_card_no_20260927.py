"""PSA 再仕入れ① の確認画面も、候補を作る時にカード番号を渡す (2026-09-27)。

イーブイex SAR 224 (820133532679) の候補に、番号の書いていない出品 (実物は 223) が6件並んだ。
ここだけ card_no / category を渡しておらず、番号なし候補の絞り込み (同じ名前が複数の番号に
あるカードでは出さない) がすり抜けていた。補URL③ は渡していたので出ていなかった。
"""
import os
import re

SRC = open(os.path.join(os.path.dirname(__file__), "..", "tools", "psa_resource_gate.py"),
           encoding="utf-8").read()


def test_every_call_passes_card_no():
    calls = [m.start() for m in re.finditer(r"(?<!def )_build_visual_candidates\(", SRC)]
    assert calls
    for i in calls:
        body = SRC[i:i + 300]
        assert "card_no=" in body, body[:120]
