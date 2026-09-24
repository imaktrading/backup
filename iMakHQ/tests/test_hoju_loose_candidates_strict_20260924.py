"""補URL: 番号なしで拾った候補は、レアリティ必須・別番号/海外版/他社鑑定を外す (2026-09-24)。
ユーザー報告「補URL③入れ替えで、目視で仕入候補が違うケースが多い」「同じ仕入候補が連続で並んでいる」。"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
import mercari_psa_resource as M                               # noqa: E402


def ok(t, c, r):
    return M.is_psa10(t) and M.loose_title_ok(t, c, r)


def test_same_name_different_card_is_dropped():
    # 1文字のレアリティ (S/R) は見分けに使わない = 目視に任せる (ユーザー「違うのが並ぶのはいい」)
    assert ok("PSA10 ライチュウ クラシック", "SV4A-237", "S")
    assert not ok("PSA10 ヨマワル C", "237/190", "AR")                                   # 2文字は必須
    assert not ok("【PSA10】デンヂムシ AR 001/071", "SV5M-076", "AR")                   # 別の番号
    assert ok("【PSA10】デンヂムシ AR 076/071 ポケモンカード", "SV5M-076", "AR")
    assert ok("ポケモンカード デンヂムシ AR PSA10", "SV5M-076", "AR")
    assert ok("PSA10 ヨマワル AR", "237/190", "AR")


def test_foreign_and_other_graders_are_dropped():
    assert not ok("英語版【PSA10】そらをとぶピカチュウV RR 25th 海外版", "S8A-020", "RR")
    assert not ok("【PCG10鑑定品】デデンネ AR M3-085/080（同PSA10）", "M3-085", "AR")


def test_display_side_uses_the_same_check_and_pending_dedup():
    g = open(os.path.join(HERE, "..", "tools", "psa_resource_gate.py"), encoding="utf-8").read()
    assert "_mpl2.loose_title_ok(" in g and "and _loose_ok(t)]" in g
    h = open(os.path.join(HERE, "..", "tools", "psa_hoju_fill.py"), encoding="utf-8").read()
    i = h.index("for _p in _pend:")
    assert '_have.add(_norm_url(_p["url"]))' in h[i:i + 300]
    assert "ctx.get(\"ng_by_iid\")" in h[i - 900:i]


def test_name_with_suffix_or_region_is_another_card():
    assert not M.loose_title_ok("PSA10カビゴンGX PROMO SM-P", "SM10-076", "R", "カビゴン")
    assert not M.loose_title_ok("PSA10 ライチュウ&アローラライチュウGX RR", "SV4A-237", "S", "ライチュウ")
    assert M.loose_title_ok("PSA10 カビゴン 076/095 R", "SM10-076", "R", "カビゴン")
    assert M.loose_title_ok("PSA10 ジガルデGX SSR", "SM8B-225", "SSR", "ジガルデGX")   # 対象自体が GX


def test_hash_number_is_checked():
    assert not M.loose_title_ok("PSA10 ライチュウ RAICHU #009 Classic", "SV4A-237", "S", "ライチュウ")
