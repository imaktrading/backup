"""確証UIに「既に自分が使っている供給」を出さない (2026-07-28).

ユーザー報告「現物と仕入候補で同じCERTが出てきている」→ 実測で原因確定:
候補に **主URL(A列)そのもの** が 18件、既存補URLと同じものが 89件 含まれていた。
主URLは同一個体なので写真も cert も現物と同じ = 目視が成立しない。
さらに同じURLを2枠が指すと、売れた時に両方が履行不能になる(Defect の入口)。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import psa_hoju_fill as P  # noqa: E402


def test_primary_url_is_dropped():
    cands = [{"url": "https://jp.mercari.com/item/m111"},
             {"url": "https://jp.mercari.com/item/m222"}]
    keep, drop = P.filter_candidates_known_urls(cands, ["https://jp.mercari.com/item/m111"])
    assert [c["url"] for c in keep] == ["https://jp.mercari.com/item/m222"]
    assert len(drop) == 1


def test_existing_aux_urls_are_dropped():
    cands = [{"url": "https://jp.mercari.com/shops/product/ABC"},
             {"url": "https://jp.mercari.com/item/m999"}]
    keep, _ = P.filter_candidates_known_urls(
        cands, ["", "https://jp.mercari.com/shops/product/ABC", ""])
    assert [c["url"] for c in keep] == ["https://jp.mercari.com/item/m999"]


def test_query_and_trailing_slash_differences_still_match():
    """?share=... や末尾スラッシュ違いで「別URL」と誤認すると素通りする。"""
    cands = [{"url": "https://jp.mercari.com/item/m111?afid=123"},
             {"url": "https://JP.mercari.com/item/m222/"}]
    keep, drop = P.filter_candidates_known_urls(
        cands, ["https://jp.mercari.com/item/m111", "https://jp.mercari.com/item/m222"])
    assert keep == []
    assert len(drop) == 2


def test_empty_known_list_keeps_everything():
    cands = [{"url": "https://jp.mercari.com/item/m111"}]
    keep, drop = P.filter_candidates_known_urls(cands, ["", None])
    assert keep == cands and drop == []


def test_norm_url():
    assert P._norm_url(" https://jp.mercari.com/item/m1?x=1#f ") == "https://jp.mercari.com/item/m1"
    assert P._norm_url(None) == ""
