# -*- coding: utf-8 -*-
"""番号がタイトルに無い候補の商品説明から番号を読む (2026-09-24)。ユーザー「商品説明に書いている場合もあるけどな」。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import mercari_desc_numbers as M  # noqa: E402
import psa_resource_gate as G  # noqa: E402


def test_extract_and_verdict():
    e = M.extract_numbers("ジンベエ リーダーパラレル OP11-021 です。PSA-10 鑑定品")
    assert e["codes"] == [["OP11", "021"]]
    assert M.verdict(e, "OP11-021") == "same"
    assert M.verdict(e, "ST01-005") == "other"
    p = M.extract_numbers("ヒビキのホウオウex RR 020/063")
    assert M.verdict(p, "SV9A-020") == "same" and M.verdict(p, "M2A-063") == "other"
    assert M.verdict(M.extract_numbers("美品です"), "OP11-021") == ""
    # 一致も別も書いてある (まとめて紹介) は決めない
    assert M.verdict(M.extract_numbers("OP11-021 と ST01-005"), "OP11-021") == ""


def test_urls_to_check_skips_fresh():
    import datetime as d
    cache = {"1": {"mercari": {"loose_cands": [[1, "https://jp.mercari.com/item/m1?x=1", "t"],
                                                [2, "https://jp.mercari.com/item/m2", "t"]]}}}
    led = {"https://jp.mercari.com/item/m1": {"at": "2026-09-20"}}
    assert M.urls_to_check(cache, led, d.date(2026, 9, 24)) == ["https://jp.mercari.com/item/m2"]


_MR = {"all_cands": [], "cands": [], "loose_cands": [(6500, "https://jp.mercari.com/item/m9", "【PSA10】ジンベエ リーダー")]}


def _urls(monkeypatch, desc, kinds):
    import mercari_psa_resource as mp
    monkeypatch.setattr(mp, "catalog_name_kinds", lambda *a, **k: kinds)
    monkeypatch.setattr(M, "load", lambda *a, **k: desc)
    monkeypatch.setattr(mp, "catalog_variants_for_cardno",
                        lambda *a, **k: [{"rarity": "L", "name_jp": "ジンベエ"}])
    return G._build_visual_candidates(dict(_MR), {}, card_no="OP11-021", category="one_piece_tcg")


def test_desc_same_number_is_shown_even_if_name_not_unique(monkeypatch):
    got = _urls(monkeypatch, {"https://jp.mercari.com/item/m9": {"codes": [["OP11", "021"]], "fracs": []}}, 32)
    assert len(got) == 1 and got[0]["desc_no"] is True and got[0]["number_ok"] is True


def test_desc_other_number_is_dropped_even_if_name_unique(monkeypatch):
    assert _urls(monkeypatch, {"https://jp.mercari.com/item/m9": {"codes": [["ST01", "005"]], "fracs": []}}, 1) == []


def test_no_desc_and_name_not_unique_is_hidden(monkeypatch):
    assert _urls(monkeypatch, {}, 32) == []
