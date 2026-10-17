# -*- coding: utf-8 -*-
"""№650: 押してから目視の画面までの待ちを測る ⏱ の行が、抽出の前・枠選びの後・照合の前・画面を出した時に出る。"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _src(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def test_timing_lines_present():
    s = _src("iMakTCG/psa_to_csv.py")
    for t in ("抽出を始めた", "抽出と枠選びが済んだ", "PSA の情報と仕入元の読み取りが済んだ"):
        assert "⏱ {datetime.now():%H:%M:%S} " + t in s
    assert _src("iMakHQ/tools/post_psa_review.py").count("目視の画面を出した") >= 1
