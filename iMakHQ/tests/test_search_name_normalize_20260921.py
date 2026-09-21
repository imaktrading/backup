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
