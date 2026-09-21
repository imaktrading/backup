"""補充の画面で安い候補を後ろに隠さない (2026-09-21)。

ユーザー「補充で出たカードが入れ替えで何で出てくるの？」。
候補を各6件で切ってから既存の補URLを除いていたので、補充では枠が既存URLに食われて
安い候補が7件目以降に隠れ、補URLが入った後の入れ替え画面で繰り上がって出ていた
(実測: 5出品が両方の画面に出た)。除く物を先に除き、安い順に並べてから切る。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import psa_resource_gate as G  # noqa: E402


def _merc(n, base=10000):
    return [(base + i * 1000, f"https://jp.mercari.com/item/m{i:011d}", "PSA10") for i in range(n)]


def test_既に付いている補URLは枠を食わない():
    cands = _merc(9)
    known = [u for _p, u, _n in cands[:6]]           # 安い6本は既に補URLに入っている
    out = G._build_visual_candidates({"all_cands": cands}, {}, exclude=known)
    urls = [c["url"] for c in out]
    assert urls == [u for _p, u, _n in cands[6:9]]   # 7〜9件目が補充の画面に出る


def test_メルカリは安い順に出る():
    cands = list(reversed(_merc(8)))                 # 高い順で来ても
    out = G._build_visual_candidates({"all_cands": cands}, {})
    prices = [c["price"] for c in out]
    assert prices == sorted(prices) and prices[0] == 10000 and len(prices) == 6


def test_スニダンも安い順で既存を除いてから切る():
    snk = [{"url": f"https://snkrdunk.com/apparels/1/used/{i}", "price": 30000 - i * 1000}
           for i in range(9)]
    known = [snk[8]["url"]]                          # 一番安いのは既に付いている
    out = G._build_visual_candidates({}, {"snkrdunk_urls": snk}, exclude=known)
    prices = [c["price"] for c in out if c["channel"] == "snkrdunk"]
    assert prices == [23000, 24000, 25000, 26000, 27000, 28000]
