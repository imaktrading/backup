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


def _src():
    return open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "tools", "newcand_confirm.py"), encoding="utf-8").read()


def test_外すのは1画面目だけ():
    """★ユーザー指示は「捨てた候補→新規出品の種」(①目視) だけ。②には入れない。

    技術的にも ② で隠すと **印が付かないまま消える** = その行は永久に未処理で残る。
    ① で外せば台帳に上がってこないし、既に台帳に居る分は人が
    「売り切れ」/「番号読めず」で閉じられる。
    """
    src = _src()
    scr1 = src[src.index("auto_aux, items, groups, over_cap"):]
    assert 'over_cost_cap(p.get("price"))' in scr1[:800]
    scr2 = src[src.index("def run_append_high("):]
    scr2 = scr2[:scr2.index("def main(")]
    assert "over_cost_cap(" not in scr2, "②(証明番号)で外している = 指示にない絞り込み"


def test_黙って捨てない():
    """除外したら必ず件数と値段を出す (silent drop 禁止)。"""
    assert _src().count("仕入値が上限を超えていて除外") == 1
