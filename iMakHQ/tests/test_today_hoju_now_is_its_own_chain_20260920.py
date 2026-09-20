"""補URL の「① 当日分」は「③ 補充」と別の流れ (2026-09-20)。

ユーザー「新規PSA自動を走らせた後、今日やることから PSA③ が消える」。
① 当日分 = 今日出した行に候補を探す / ③ 補充 = 夜に溜めた別の行を目視して書く で、
対象が別なので順番の関係が無い。新規自動を走らせると当日分が 0→17 になり、その瞬間
③ (補充 65件) が順番待ちに隠れていた (実測 2026-09-20 console_counts.json:
search.today_can=17 / confirm.ready+unjudged=65)。
"""
import os
import re

HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = open(os.path.join(HQ, "console", "static", "app.js"), encoding="utf-8").read()
BODY = APP.split("function chainOf(j) {")[1].split("function rankOf")[0]


def test_当日分は別の流れとして数える():
    assert '/当日分/.test(j.label) ? "/now"' in BODY


def test_入れ替えも別のままにする():
    """2026-09-19 の決定を壊していないこと。"""
    assert '/入れ替え/.test(j.label) ? "/swap"' in BODY


def test_PSAとUTの両方に効く():
    """当日分ボタンは PSA と UT の2つある (ラベルで判定しているので両方に効く)。"""
    panel = open(os.path.join(HQ, "control_panel.py"), encoding="utf-8").read()
    labels = re.findall(r'"label": "([^"]*当日分[^"]*)"', panel)
    assert len(labels) == 2, labels
    assert all("当日分" in l for l in labels)
