# -*- coding: utf-8 -*-
"""仕入値の列(N)が死んだ時に、現在地が **実際に鳴る** ことを証明する (失敗注入)。

2026-09-09 の実害は「壊れたこと」より **壊れたまま誰も気づかなかったこと**だった。
なので検知を足したが、**検知は「置いた」ではなく「鳴る」ことを見せないと意味がない**
(completion_must_be_proven)。ここで N1 の値を差し替えて、3つの分岐すべてを確かめる。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "tools"))
import status_now as S       # noqa: E402


def test_壊れていたら鳴る(monkeypatch):
    monkeypatch.setattr(S, "_run", lambda *a, **k: "NG|#REF!")
    out = S._cost_column()
    assert "仕入値の列(N)が死んでいます" in out
    assert "#REF!" in out
    assert "N2:N" in out                      # 直し方まで出す (見た人がすぐ動ける)


def test_正常なら黙る(monkeypatch):
    monkeypatch.setattr(S, "_run", lambda *a, **k: "OK")
    assert S._cost_column() == ""


def test_確認できない時は黙らない(monkeypatch):
    """読めなかった = 正常ではない。無言で通すと fail-OPEN になる。"""
    monkeypatch.setattr(S, "_run", lambda *a, **k: "")
    out = S._cost_column()
    assert out and "確認できませんでした" in out


def test_現在地の本体から呼ばれている():
    """関数を置いただけで main が呼んでいない、を防ぐ。"""
    src = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "tools", "status_now.py"), encoding="utf-8").read()
    body = src[src.index("def main("):]
    assert "_cost_column()" in body
