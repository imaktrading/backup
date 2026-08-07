#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mercari_psa_resource 回帰テスト (2026-06-09)。

ユーザー指摘起点の修正をカバー:
  ② 違うカード     → _name_matches_card の token連続一致 (promo番号の遊戯王誤マッチ消滅)
  ③ オークション   → parse_mercari_items が cell内マーカーで auction を除外
  ④ 相当           → is_psa10 が「相当」を除外
  画像検索FB        → parse_image_search_results (モーダル結果パース)
  検索語構築        → build_card_query / _extract_card_no / _ebay_item_id
"""
import importlib.util
import os

_MOD = os.path.join(os.path.dirname(__file__), "..", "tools", "mercari_psa_resource.py")
_spec = importlib.util.spec_from_file_location("mercari_psa_resource", _MOD)
m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m)


def _cell(item_type, name, price, href, auction=False):
    """item-cell 1つ分のHTML断片 (auction=True で現在価格/残り時間マーカー入り)。"""
    extra = "<span>残り時間</span><span>現在価格</span>" if auction else ""
    return (
        f'data-testid="item-cell" class="x">'
        f'<a href="{href}" data-testid="thumbnail-link">'
        f'<div class="merItemThumbnail" role="img" '
        f'aria-label="{name}の画像 {price}円" id="x" itemtype="{item_type}">'
        f'{extra}<img alt="{name}のサムネイル"></div></a></li>'
    )


# ---------- ② token連続一致 (promo番号の誤マッチ防止) ----------
def test_card_tokens():
    assert m._card_tokens("OP11-106") == ["OP11", "106"]
    assert m._card_tokens("P-041") == ["P", "041"]
    assert m._card_tokens("ST07-008") == ["ST07", "008"]


def test_name_matches_card_token_sequence():
    # 正規表記 (番号がトークン分離) は一致
    assert m._name_matches_card("モンキーDルフィ スタデ P-041 4枚", "P-041") is True
    assert m._name_matches_card("ゼウス OP11-106 プロモ", "OP11-106") is True
    assert m._name_matches_card("【PSA10】ジュエリー・ボニー {EB02-015}", "EB02-015") is True


def test_name_matches_card_rejects_yugioh_substring():
    # 2026-06-09 実害: P-041 が遊戯王 FOTB-JP041 / STB1-P041 (=JP041, 1トークン) に誤マッチ
    assert m._name_matches_card("遊戯王 ブレイズ・キャノン FOTB-JP041", "P-041") is False
    assert m._name_matches_card("スクラップ・ツイン STB1-P041", "P-041") is False
    # 番号結合表記 (OP11106) も別トークン扱いで弾く (fail-closed)
    assert m._name_matches_card("ゼウス OP11106 promo", "OP11-106") is False
    # 空番号は不採用
    assert m._name_matches_card("なにか PSA10", "") is False


# ---------- ③ オークション除外 ----------
FIXTURE = "<html>" + "".join([
    # 最安だがオークション (itemtype は MERCARI でも除外されるべき)
    _cell("ITEM_TYPE_MERCARI", "サボ OP11-106 PSA10", "3,000", "/item/mAUC11", auction=True),
    # 別カード (id-strict で除外)
    _cell("ITEM_TYPE_MERCARI", "ルフィ OP11-001 PSA10", "4,000", "/item/mWRONG2"),
    # 本命 (通常出品)
    _cell("ITEM_TYPE_MERCARI", "サボ OP11-106 PSA10", "6,000", "/item/mRIGHT3"),
    # Shops の本命 (高い)
    _cell("ITEM_TYPE_BEYOND", "サボ OP11-106 PSA10", "7,000", "/shops/product/SABO4"),
]) + "</html>"


def test_parse_excludes_auction_by_marker():
    items = m.parse_mercari_items(FIXTURE)
    # オークション1件を除外 → 3件、価格に3000(auction)を含まない
    assert len(items) == 3
    assert 3000 not in [it["price"] for it in items]
    assert [it["price"] for it in items] == [4000, 6000, 7000]


def test_parse_aligns_name_price_href():
    items = m.parse_mercari_items(FIXTURE)
    right = items[1]
    assert right["name"] == "サボ OP11-106 PSA10"
    assert right["price"] == 6000
    assert right["href"] == "https://jp.mercari.com/item/mRIGHT3"
    assert items[2]["href"] == "https://jp.mercari.com/shops/product/SABO4"


def test_pick_skips_auction_and_wrong_card():
    best = m.pick_cheapest_psa10(m.parse_mercari_items(FIXTURE), "OP11-106")
    # ¥3000オークション と ¥4000別カード を飛ばして本命 ¥6000
    assert best is not None and best[0] == 6000
    assert best[1] == "https://jp.mercari.com/item/mRIGHT3"


def test_pick_none_when_no_match():
    assert m.pick_cheapest_psa10(m.parse_mercari_items(FIXTURE), "OP99-999") is None


# ---------- ④ 相当除外 ----------
def test_is_psa10_excludes_souto():
    assert m.is_psa10("サボ OP11-106 PSA10") is True
    assert m.is_psa10("サボ OP11-106 psa10相当") is False
    assert m.is_psa10("リザードンex PSA10相当品") is False


def test_pick_skips_souto():
    html = "<html>" + "".join([
        _cell("ITEM_TYPE_MERCARI", "サボ OP11-106 psa10相当", "2,000", "/item/mSOUTO"),
        _cell("ITEM_TYPE_MERCARI", "サボ OP11-106 PSA10", "6,000", "/item/mREAL"),
    ]) + "</html>"
    best = m.pick_cheapest_psa10(m.parse_mercari_items(html), "OP11-106")
    assert best is not None and best[0] == 6000


# ---------- 画像検索モーダル パース ----------
def test_parse_image_search_results():
    modal = "".join([
        '<a data-location="image_search:similar_looks_modal:item_thumbnail" '
        'href="/item/m111"><div aria-label="2,728円"></div></a>',
        '<a data-location="image_search:similar_looks_modal:item_thumbnail" '
        'href="/shops/product/ABC"><div aria-label="売り切れ 777円"></div></a>',
    ])
    res = m.parse_image_search_results(modal)
    assert len(res) == 2
    assert res[0] == {"href": "https://jp.mercari.com/item/m111", "sold": False, "price": 2728}
    assert res[1]["sold"] is True and res[1]["price"] == 777


# ---------- 検索語/ID 抽出 ----------
def test_extract_card_no():
    assert m._extract_card_no("PSA 10 One Piece TCG #OP11-106 Zeus", "") == "OP11-106"
    assert m._extract_card_no("...", "EB02-015") == "EB02-015"
    assert m._extract_card_no("PSA 10 Promo #P-041 Luffy", "") == "P-041"


def test_ebay_item_id():
    assert m._ebay_item_id("https://www.ebay.com/itm/358596483319") == "358596483319"
    assert m._ebay_item_id("") == ""


def test_build_card_query_has_number():
    q = m.build_card_query("PSA 10 One Piece TCG #EB02-015 Jewelry Bonney", "")
    assert q["card_no"] == "EB02-015"
    assert q["kw"].startswith("PSA10 ") and "EB02-015" in q["kw"]
