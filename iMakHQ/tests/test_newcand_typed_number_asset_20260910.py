# -*- coding: utf-8 -*-
"""目視で入れた番号を資産にする (2026-09-10 ユーザー指摘).

> 過去カード番号を入れて確定させたのに、またカード番号を入れないといけないのが出てきている
> 資産化されていない証拠では?
> スニダンにもタイトルはあります。

3つ重なっていた:
  1. スニダンの検索APIは name (番号が [SV2a 201/165] の形で入る) を返しているのに
     保存していなかった → 候補のタイトルが空 → 番号が読めない
  2. 打った番号を **出品URLごと** に覚えていた → 同じカードの別の出品でまた聞く
  3. まとめる鍵が card_no だけ → 番号が読めない候補は1件もまとまらず、
     同じカードが並ぶ (実測: 20件中6件が同じカード = 同じ番号を6回打たされる)
"""
import os
import sys

TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
sys.path.insert(0, TOOLS)

import newcand_confirm as N          # noqa: E402


def test_card_id_comes_from_the_url():
    assert N.snkrdunk_card_id("https://snkrdunk.com/apparels/165931/used/49618379") == "165931"
    assert N.snkrdunk_card_id("https://jp.mercari.com/item/m1") == ""
    assert N.snkrdunk_card_id("") == ""


def test_typed_number_is_reused_for_the_same_card():
    """別の出品でも、同じカードなら過去に打った番号が効く。"""
    u1 = "https://snkrdunk.com/apparels/165931/used/1"
    u2 = "https://snkrdunk.com/apparels/165931/used/2"
    assert N.typed_no_for(u2, {u1: "ST13-015"}, {"165931": "ST13-015"}) == "ST13-015"


def test_exact_url_wins():
    u = "https://snkrdunk.com/apparels/1/used/2"
    assert N.typed_no_for(u, {u: "A-1"}, {"1": "B-2"}) == "A-1"


def test_unknown_card_returns_empty():
    assert N.typed_no_for("https://jp.mercari.com/item/m1", {}, {}) == ""


def test_snkrdunk_title_comes_from_the_cache():
    """スニダンの商品名を候補のタイトルに使う (番号が読める)。"""
    c = {"1": {"snkrdunk": {"card_name": "ポケモンカード [SV2a 201/165] ピカチュウ",
                            "psa10_listings": [{"price": 100, "image": "i",
                                                "url": "https://snkrdunk.com/apparels/1/used/2"}]}}}
    got = N.url_title_map(c)["https://snkrdunk.com/apparels/1/used/2"]
    assert got[1] == "ポケモンカード [SV2a 201/165] ピカチュウ"
    assert N.extract_card_no(got[1]) == "201/165"


def test_scraper_keeps_the_name():
    src = open(os.path.join(TOOLS, "snkrdunk_psa_resource.py"), encoding="utf-8").read()
    assert '_meta["name"] = (it.get("name") or "").strip()' in src
    assert src.count('"card_name"') >= 3, "3つの戻り全部に付けること"


def test_grouping_falls_back_to_the_card_when_the_number_is_unknown():
    src = open(os.path.join(TOOLS, "newcand_confirm.py"), encoding="utf-8").read()
    assert 'gkey = no or (("sd:" + snkrdunk_card_id(p["url"]))' in src
    assert 'groups.get(it.get("_gkey") or "", [])' in src


def test_official_product_number_wins_over_the_name():
    """番号は項目 (productNumber) を第一に使う (名前の解析は表記ゆれで外れる)。"""
    c = {"1": {"snkrdunk": {"card_number": "OP01-120",
                            "card_name": "ちがう名前 [XX-999]",
                            "psa10_listings": [{"url": "u1"}]}}}
    assert N.snkrdunk_number_map(c) == {"u1": "OP01-120"}


def test_falls_back_to_the_name_when_no_field():
    c = {"1": {"snkrdunk": {"card_name": "ポケカ [SV2a 201/165] ピカ",
                            "psa10_listings": [{"url": "u2"}]}}}
    assert N.snkrdunk_number_map(c) == {"u2": "201/165"}


def test_neither_means_ask_the_human():
    c = {"1": {"snkrdunk": {"psa10_listings": [{"url": "u3"}]}}}
    assert N.snkrdunk_number_map(c) == {}


def test_scraper_keeps_the_product_number():
    src = open(os.path.join(TOOLS, "snkrdunk_psa_resource.py"), encoding="utf-8").read()
    assert '_meta["product_number"] = (it.get("productNumber") or "").strip()' in src
    assert src.count('"card_number"') >= 3


def test_viewer_counts_where_the_number_came_from():
    """「次から精度が上がる」を実測で言えるように出どころを数える。"""
    src = open(os.path.join(TOOLS, "newcand_confirm.py"), encoding="utf-8").read()
    assert "カード番号の出どころ" in src
    assert '"スニダンの項目"' in src
