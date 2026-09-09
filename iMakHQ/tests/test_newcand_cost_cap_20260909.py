# -*- coding: utf-8 -*-
"""種 (捨てた候補→新規出品) から **仕入値が上限を超えた分**を外す (2026-09-09 ユーザー確定)。

    ユーザー「捨てた候補→新規出品の種 だけど、価格上限入っている？」→「外そう、時間の無駄だし」

上限を超えた種は、目視して証明番号まで打っても **生成の段階で COST-CAP で落ちる**
(`psa_to_csv.py:3580` が「枠を選ぶ前」に同じ判定をしている)。落ちると分かっている物を
人に見せない。2026-09-05 に生成側でやった「上限は枠を選ぶ前に見る」と同じ話。

実測 2026-09-09: 種40件のうち4件が上限超 (¥85,722 / ¥118,450 / ¥128,000 / ¥199,800)。

★しきい値はここで持たない。`global.yaml` の cost_sanity を pricing_engine 経由で読む
  (二重定義しない = 上限を変えた時に片方だけ古くなるのを防ぐ)。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "tools"))
import newcand_confirm as N     # noqa: E402


def test_上限を超えていたら外す():
    assert N.over_cost_cap(199800) is True
    assert N.over_cost_cap("¥118,450") is True


def test_上限以下は通す():
    assert N.over_cost_cap(5000) is False
    assert N.over_cost_cap("69,999") is False


def test_値段が分からない時は止めない():
    """fail-open。値段が無い行は別の門 (価格なし=$100固定の防止) で扱う。"""
    assert N.over_cost_cap(None) is False
    assert N.over_cost_cap("") is False
    assert N.over_cost_cap("abc") is False


def test_しきい値を自分で持っていない():
    """上限の数値をこのファイルに書かない (global.yaml と二重定義しない)。"""
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "tools", "newcand_confirm.py"), encoding="utf-8").read()
    body = src[src.index("def over_cost_cap("):]
    body = body[:body.index("def build_cert_html(")]
    assert "cost_sanity" in body and "pricing_engine" in body
    assert "70000" not in body, "上限の数値をコードに焼いている"


def test_両方の画面で外している():
    """①目視 と ②証明番号 の両方。片方だけだと結局 人が触ることになる。"""
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "tools", "newcand_confirm.py"), encoding="utf-8").read()
    scr1 = src[src.index("auto_aux, items, groups, over_cap"):]
    assert "over_cost_cap(p.get(\"price\"))" in scr1[:800]
    scr2 = src[src.index("def run_append_high("):]
    assert "over_cost_cap(it.get(\"price\"))" in scr2[:1200]


def test_黙って捨てない():
    """除外したら必ず件数と値段を出す (silent drop 禁止)。"""
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "tools", "newcand_confirm.py"), encoding="utf-8").read()
    assert src.count("仕入値が上限を超えていて除外") == 2
