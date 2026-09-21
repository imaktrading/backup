"""補URL 検索語は市場の書き方に寄せる (2026-09-21 休み中31件の深堀)。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import mercari_psa_resource as mp  # noqa: E402


def test_全角Dは半角にする():
    assert mp.search_name("モンキー・Ｄ・ルフィ") == "モンキー・D・ルフィ"


def test_空白は詰める():
    assert mp.search_name("アローラ ナッシーV") == "アローラナッシーV"


def test_空は空():
    assert mp.search_name(None) == ""


def test_名前照合は全角半角を吸収():
    items = [{"price": 5000, "href": "u1", "name": "PSA10 モンキー・D・ルフィ L"}]
    assert mp.pick_psa10_loose_candidates(items, "モンキー・Ｄ・ルフィ")


def test_番号なし検索語はレアリティ付き():
    c = {"name_jp": "ヨマワル", "hint": ["", "", "", "", "AR", "ヨマワル"]}
    assert mp.loose_search_kw(c) == "PSA10 ヨマワル AR"
    assert mp.loose_search_kw({"name_jp": "ゲンガー", "hint": ["", "", "", "", "U"]}) == "PSA10 ゲンガー"


def test_レアリティが違う出品は拾わない():
    items = [{"price": 3000, "href": "a", "name": "PSA10 ヨマワル C"},
             {"price": 4000, "href": "b", "name": "PSA10 ヨマワル AR ポケモンカード"}]
    got = mp.pick_psa10_loose_candidates(items, "ヨマワル", rarity="AR")
    assert [t[1] for t in got] == ["b"]
