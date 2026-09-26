"""補URL: ポケモンのマスターボールミラーを他のミラーと混ぜない (2026-09-27)。

ユーザー「A (リバースホロ) は B (マスターボールミラー) と違うよね」。
ブラッキー SV8a-092 のマスターボールミラー (鑑定 124104675) の補URL③に、通常ミラーの PSA10 が並んだ。
カタログは番号1つ (公式も分かれていない) なので、版は PSA の鑑定データから取る。
PSA の「REVERSE HOLO」だけの物には モンボ も混ざる (実測) ので、確かな マスターボールか否か だけで絞る。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import mercari_psa_resource as mp  # noqa: E402
import psa_hoju_fill as H  # noqa: E402
from psa_resource_confirm import split_subject_variety  # noqa: E402


def test_mirror_kind_from_psa():
    assert mp.mirror_kind("MASTER BALL REVERSE HOLO") == "master"
    assert mp.mirror_kind("UMBREON MASTER BALL REVERSE HOLO") == "master"
    assert mp.mirror_kind("REVERSE HOLO") == "mirror"
    assert mp.mirror_kind("POKE BALL REVERSE HOLO") == "mirror"
    assert mp.mirror_kind("ALTERNATE ART") == ""
    assert mp.mirror_kind("") == ""


def test_master_listing_needs_master_in_title():
    k = "master"
    assert mp.mirror_title_conflicts(k, "【PSA10】ブラッキー SV8a 092/187 モンスターボールミラー")
    assert mp.mirror_title_conflicts(k, "★PSA10★【ブラッキー/ミラー/SV8a】UMBREON 092/187")
    assert not mp.mirror_title_conflicts(k, "【PSA10】ブラッキー マスターボールミラー sv8a 092/187")
    assert not mp.mirror_title_conflicts(k, "【PSA10】【マスボ】ビクティニ 012/086")
    assert not mp.mirror_title_conflicts(k, "PSA10 UMBREON MASTER BALL 092")


def test_other_mirror_drops_master_only():
    k = "mirror"
    assert mp.mirror_title_conflicts(k, "PSA10 ブラッキー マスターボールミラー 092/187")
    # PSA の REVERSE HOLO にはモンボも混ざるので、モンボ・無記載は外さない
    assert not mp.mirror_title_conflicts(k, "psa10 チヲハウハネ モンボ")
    assert not mp.mirror_title_conflicts(k, "PSA10 レックウザ 127/193")


def test_unknown_kind_drops_nothing():
    assert not mp.mirror_title_conflicts("", "PSA10 ブラッキー マスターボールミラー")


def test_subject_split_keeps_master_ball():
    assert split_subject_variety("UMBREON MASTER BALL REVERSE HOLO") == \
        ("UMBREON", "MASTER BALL REVERSE HOLO")
    assert split_subject_variety("PIKACHU REVERSE HOLO") == ("PIKACHU", "REVERSE HOLO")


def test_search_result_filtered_before_cache():
    m = {"best": [9000, "u1", "ブラッキー モンスターボールミラー"],
         "cands": [[9000, "u1", "ブラッキー モンスターボールミラー"],
                   [30000, "u2", "ブラッキー マスターボールミラー"]]}
    out = H.filter_mercari_result_by_mirror(m, "master", mp)
    assert [x[1] for x in out["cands"]] == ["u2"]
    assert out["best"][1] == "u2"
    assert H.filter_mercari_result_by_mirror(m, "", mp) is m


def test_display_candidates_filtered():
    keep, drop = H.filter_candidates_by_mirror(
        [{"name": "ブラッキー モンスターボールミラー"}, {"name": "ブラッキー マスボ"}], "master", mp)
    assert [c["name"] for c in keep] == ["ブラッキー マスボ"] and len(drop) == 1


def test_wired_into_search_and_display():
    src = open(H.__file__, encoding="utf-8").read()
    assert 'q["kw"] = f"{q[\'kw\']} マスターボール"' in src
    assert "m = filter_mercari_result_by_mirror(mercari_res.get(i), q.get(\"mirror\"), mp)" in src
    assert "filter_candidates_by_mirror(cands, mirror_kind_for_target(t, mp), mp)" in src
