#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mercari_psa_resource の per-cell パーサ回帰テスト (2026-06-09)。

ユーザー指摘3点のうちメルカリ側2点をカバー:
  ② 2行目が違うカード → _name_matches_card による id-strict (別カード除外)
  ③ オークション混入 → parse_mercari_items が itemtype 通常出品のみ採用 (auction 除外)

実DOM(c:/tmp/mercari_dump.html 由来)の構造を模した最小 fixture で検証。
"""
import importlib.util
import os

_MOD = os.path.join(os.path.dirname(__file__), "..", "tools", "mercari_psa_resource.py")
_spec = importlib.util.spec_from_file_location("mercari_psa_resource", _MOD)
m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m)


def _cell(item_type, name, price, href):
    """item-cell 1つ分のHTML断片 (href→aria-label→itemtype の実DOM順)。"""
    return (
        f'data-testid="item-cell" class="x">'
        f'<a href="{href}" data-testid="thumbnail-link">'
        f'<div class="merItemThumbnail" role="img" '
        f'aria-label="{name}の画像 {price}円" id="x" itemtype="{item_type}">'
        f'<img alt="{name}のサムネイル"></div></a></li>'
    )


# サボ OP11-106 を探す状況: 最安はオークション(除外), 次に別カード(除外), 本命は3番目
FIXTURE = "<html><body>" + "".join([
    _cell("ITEM_TYPE_AUCTION", "サボ OP11-106 PSA10", "3,000", "/item/mAUC111"),
    _cell("ITEM_TYPE_MERCARI", "ルフィ OP11-001 PSA10", "4,000", "/item/mWRONG22"),
    _cell("ITEM_TYPE_MERCARI", "サボ OP11-106 PSA10", "6,000", "/item/mRIGHT33"),
    _cell("ITEM_TYPE_BEYOND", "サボ OP11-106 PSA10", "7,000", "/shops/product/SABO44"),
]) + "</body></html>"


def test_parse_excludes_auction():
    items = m.parse_mercari_items(FIXTURE)
    # 4セル中オークション1件を除外 → 3件
    assert len(items) == 3
    assert "ITEM_TYPE_AUCTION" not in {it["type"] for it in items}
    assert {it["type"] for it in items} == {"ITEM_TYPE_MERCARI", "ITEM_TYPE_BEYOND"}


def test_parse_aligns_name_price_href():
    items = m.parse_mercari_items(FIXTURE)
    # DOM順 = 価格昇順、name·price·href が同一セルで対応
    assert [it["price"] for it in items] == [4000, 6000, 7000]
    right = items[1]
    assert right["name"] == "サボ OP11-106 PSA10"
    assert right["price"] == 6000
    assert right["href"] == "https://jp.mercari.com/item/mRIGHT33"
    # Shops は /shops/product/ href
    assert items[2]["href"] == "https://jp.mercari.com/shops/product/SABO44"


def test_pick_skips_auction_and_wrong_card():
    items = m.parse_mercari_items(FIXTURE)
    best = m.pick_cheapest_psa10(items, m._card_token("PSA10 OP11-106"))
    # ¥3000オークション(除外) と ¥4000別カード(id-strict除外) を飛ばし、本命 ¥6000 を選ぶ
    assert best is not None
    assert best[0] == 6000
    assert best[1] == "https://jp.mercari.com/item/mRIGHT33"
    assert "OP11-106" in best[2]


def test_pick_none_when_no_card_match():
    # 該当カード番号が一切無ければ採用しない (fail-closed)
    items = m.parse_mercari_items(FIXTURE)
    assert m.pick_cheapest_psa10(items, m._card_token("PSA10 OP99-999")) is None


def test_card_token_and_match():
    assert m._card_token("PSA10 OP11-106") == "OP11106"
    assert m._card_token("PSA 10 ST07-008") == "ST07008"
    # ハイフン/空白/全角差を吸収して照合
    assert m._name_matches_card("サボ OP11-106 PSA10", "OP11106") is True
    assert m._name_matches_card("ルフィ OP11-001", "OP11106") is False
    # 極短トークンは誤マッチ源 → 不採用
    assert m._name_matches_card("なんとか 12", "12") is False


def test_card_token_strips_only_psa10_prefix():
    # "PSA10 " のみ除去、カード番号は保持
    assert m._card_token("PSA10 EB01-057") == "EB01057"


def test_is_psa10_excludes_souto():
    # 「PSA10相当」= 未鑑定同等品 → 本物PSA10でないので除外 (2026-06-09 ユーザー指摘)
    assert m.is_psa10("サボ OP11-106 PSA10") is True
    assert m.is_psa10("サボ OP11-106 psa10相当") is False
    assert m.is_psa10("リザードンex PSA10相当品") is False


def test_pick_skips_souto_equivalent():
    # 「相当」品が最安でも採用せず、本物PSA10を選ぶ (fail-closed)
    html = "<html>" + "".join([
        _cell("ITEM_TYPE_MERCARI", "サボ OP11-106 psa10相当", "2,000", "/item/mSOUTO1"),
        _cell("ITEM_TYPE_MERCARI", "サボ OP11-106 PSA10", "6,000", "/item/mREAL22"),
    ]) + "</html>"
    items = m.parse_mercari_items(html)
    best = m.pick_cheapest_psa10(items, m._card_token("PSA10 OP11-106"))
    assert best is not None and best[0] == 6000
    assert best[1] == "https://jp.mercari.com/item/mREAL22"
