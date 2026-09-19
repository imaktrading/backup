"""今は売り切れだが再入荷する仕入元は、落とさず一番後ろに回す (2026-09-19)。

監視くんの判断: メルカリShops / Amazon 等は売り切れても また買えるので
「買えないURL」台帳には載せない (載せると仕入元を永久に失う)。実測 1,185件。
出品くん側は落とさないが、そのまま前に出すと人の手間だけかかるので後ろに回し、
画面に「今は売り切れ (再入荷あり)」と出す。
"""
import sys

sys.path.insert(0, r"C:/dev/iMak/iMakHQ/tools")
import psa_resource_gate as G
import mercari_psa_resource as M
import psa_resource_confirm as C


def test_売り切れ再入荷ありは後ろに回る(monkeypatch):
    monkeypatch.setattr(M, "load_restockable_sold", lambda *a, **k: {"https://a": {}})
    mr = {"all_cands": [[100, "https://a", "A"], [200, "https://b", "B"]]}
    got = G._build_visual_candidates(mr, {})
    assert [c["url"] for c in got] == ["https://b", "https://a"]   # 安い方でも後ろ
    assert got[-1]["sold_restockable"] is True
    assert "sold_restockable" not in got[0]


def test_台帳が無ければ今までどおり(monkeypatch):
    monkeypatch.setattr(M, "load_restockable_sold", lambda *a, **k: {})
    mr = {"all_cands": [[100, "https://a", "A"], [200, "https://b", "B"]]}
    assert [c["url"] for c in G._build_visual_candidates(mr, {})] == ["https://a", "https://b"]


def test_画面に印を出す():
    src = open(r"C:/dev/iMak/iMakHQ/tools/psa_resource_confirm.py", encoding="utf-8").read()
    assert "sold_restockable" in src
    assert "今は売り切れ (再入荷あり)" in src
