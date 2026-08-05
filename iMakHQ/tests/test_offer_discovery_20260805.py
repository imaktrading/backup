# -*- coding: utf-8 -*-
"""オファーの取り方 — GetBestOffers 単体で ItemID ごと取る (2026-08-05).

実害 (2026-08-05 ユーザー報告「2件のオファーを読み込まない」):
  `fetch_offers` は GetMyeBaySelling の ActiveList を舐めて
  `<BestOfferCount>` が 1 以上の listing を探していた。しかし **この tag は
  ActiveList のレスポンスに存在しない** (実測: 200件中 0 個)。
  条件が全件 false になるので、オファーが実在しても **常に 0件** だった。

  さらに ActiveList の `TotalNumberOfPages` は他の list (Scheduled/Sold/Unsold) の
  分も返る (実測 ['1','24','1','6'])。先頭を拾って break するので、仮に tag が
  あっても **200/1824 件しか見ない**実装でもあった。

正しい取り方:
  GetBestOffers は ItemID を省くと全 listing 分を返し、
  ItemBestOffersArray > ItemBestOffers > (Item.ItemID/Title + BestOfferArray)
  の形で **ItemID も一緒に**返る。1コールで足りる。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
from offer_calc import parse_best_offers  # noqa: E402

#: 2026-08-05 の実レスポンスの形 (2件・うち1件は UK ミラーで GBP)
REAL = """<GetBestOffersResponse><Ack>Success</Ack><ItemBestOffersArray>
<ItemBestOffers><Item><ItemID>358853881133</ItemID>
<Title>PSA 10 One Piece Japanese Booster Vol.2 #OP09-020 Come On!! We&apos;ll Fight You!!</Title>
</Item><BestOfferArray><BestOffer><BestOfferID>1</BestOfferID>
<Price currencyID="USD">250.0</Price><Status>Pending</Status>
<Buyer><UserID>brei-9443</UserID><FeedbackScore>1</FeedbackScore>
<CountryName>CH</CountryName></Buyer>
<ExpirationTime>2026-08-05T13:21:59.000Z</ExpirationTime><Quantity>1</Quantity>
</BestOffer></BestOfferArray></ItemBestOffers>
<ItemBestOffers><Item><ItemID>358785694097</ItemID>
<Title>Ichiban Kuji Last One Gundam Barbatos &amp; Bustisan</Title>
</Item><BestOfferArray><BestOffer><BestOfferID>2</BestOfferID>
<Price currencyID="GBP">45.0</Price><Status>Pending</Status>
<Buyer><UserID>xfunghk</UserID><FeedbackScore>134</FeedbackScore>
<CountryName>GB</CountryName></Buyer>
<ExpirationTime>2026-08-05T11:46:52.000Z</ExpirationTime><Quantity>1</Quantity>
</BestOffer></BestOfferArray></ItemBestOffers>
</ItemBestOffersArray><PaginationResult><TotalNumberOfPages>1</TotalNumberOfPages>
</PaginationResult></GetBestOffersResponse>"""


class TestParseBestOffers:
    def test_finds_both_offers(self):
        """★本体: 実レスポンスから 2件 取れること (報告された症状そのもの)."""
        got = parse_best_offers(REAL)
        assert set(got) == {"358853881133", "358785694097"}

    def test_keeps_item_id_which_getbestoffers_does_return(self):
        """旧コメント『GetBestOffers 単体では ItemID が返らない』は誤り."""
        assert "358853881133" in parse_best_offers(REAL)

    def test_unescapes_title(self):
        got = parse_best_offers(REAL)
        assert got["358853881133"]["title"].endswith("We'll Fight You!!")
        assert "&" in got["358785694097"]["title"]

    def test_offer_xml_is_kept_for_downstream(self):
        """価格/buyer/期限は呼び出し側が同じ XML から読むので、持ち回れること."""
        x = parse_best_offers(REAL)["358785694097"]["xml"]
        assert '<Price currencyID="GBP">45.0</Price>' in x
        assert "<UserID>xfunghk</UserID>" in x

    def test_accumulates_across_pages(self):
        acc = {}
        parse_best_offers(REAL, acc)
        parse_best_offers(REAL, acc)          # 2ページ目に同じ item が来ても壊れない
        assert len(acc) == 2

    def test_empty_response_is_empty_dict(self):
        assert parse_best_offers("") == {}
        assert parse_best_offers("<GetBestOffersResponse><Ack>Success</Ack>"
                                 "</GetBestOffersResponse>") == {}

    def test_block_without_item_id_is_skipped(self):
        assert parse_best_offers("<ItemBestOffers><Title>x</Title></ItemBestOffers>") == {}


class TestOldDiscoveryIsGone:
    """ActiveList + BestOfferCount に戻さないための番人."""

    def test_source_no_longer_filters_on_best_offer_count(self):
        src = open(os.path.join(os.path.dirname(__file__), "..", "tools", "offer_calc.py"),
                   encoding="utf-8").read()
        head = src[:src.find("def parse_best_offers")]
        body = src[src.find("def fetch_offers"):src.find("def fetch()")]
        code = "\n".join(ln for ln in (head + body).splitlines()
                         if not ln.strip().startswith("#"))
        assert "BestOfferCount" not in code, \
            "ActiveList に BestOfferCount は無い。条件にすると常に0件になる"
