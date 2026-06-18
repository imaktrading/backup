"""Regression: 2026-06-18 — PSA再仕入れ照合の研究キャッシュ(当日Mercari/SNKRDUNK再利用)。

再走で全件再スクレイプ(Selenium・遅い・BANリスク)するのは無駄。当日の結果を itemID キーで
キャッシュし、同日再走は再利用、未キャッシュのみスクレイプ。--fresh で無視。combine は
json往復(tuple→list)しても同結果。
"""
import importlib.util
import json
from pathlib import Path

_GATE = Path(__file__).resolve().parent.parent / "iMakHQ" / "tools" / "psa_resource_gate.py"
import sys
sys.path.insert(0, str(_GATE.parent))
_spec = importlib.util.spec_from_file_location("psa_resource_gate_rc", _GATE)
g = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(g)


def test_gate_has_research_cache():
    src = _GATE.read_text(encoding="utf-8")
    assert "psa_research_cache.json" in src
    assert "--fresh" in src and "_cache_hit" in src
    assert 'c.get("date") == _today' in src           # 当日のみ再利用(古いは再スクレイプ)
    assert "新規スクレイプ" in src and "キャッシュ再利用" in src


def test_combine_survives_cache_json_roundtrip():
    best = (40000, "https://jp.mercari.com/item/m1", "ナミ")
    snk = {"available": True, "psa10_price_jpy": 42000,
           "psa10_listings": [{"price": 42000, "url": "https://s/1"}]}
    mr = {"best": best, "cands": [best]}
    c1 = g.combine(mr["best"], snk, mercari_cands=mr["cands"])
    mr2, snk2 = json.loads(json.dumps(mr)), json.loads(json.dumps(snk))   # キャッシュ往復(tuple→list)
    c2 = g.combine(mr2["best"], snk2, mercari_cands=mr2["cands"])
    assert c1["resourceable"] == c2["resourceable"] is True
    assert c1["cheapest_jpy"] == c2["cheapest_jpy"]
    assert c1["mercari_url"] == c2["mercari_url"]
