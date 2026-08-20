"""tests/test_rakuten_gacha - 楽天ガチャポン収集の判定ロジック.

2026-08-19 新設。 実測 (POC) で分かった事をテストに固定する:
  - 在庫マーク (availability) は使えない。 予約品も InStock を返す
  - 即納の判定は **配送予定に発送日があるか**。 無ければ通さない (fail-closed)
  - HIGH の N/P は数式なので **中間スプシでも N/P には書かない**
"""
from __future__ import annotations

import pytest

from scrapers.rakuten_item import extract_shipping, judge
from scrapers.rakuten_search import (
    is_complete_set, looks_preorder, parse_results, parse_total,
)
from sheet_writer_amazon import (
    COL_CATEGORY, COL_CONDITION, COL_IMAGES, COL_PRICE, COL_TITLE, COL_URL,
)
from sheet_writer_rakuten import CATEGORY, COL_CURRENT_PRICE, build_row, dedupe_key

pytestmark = pytest.mark.offline

COL_PURCHASE_PRICE = 14  # N (HIGH では ARRAYFORMULA)
COL_CTR = 16             # P (HIGH では countif)


# --------------------------------------------------------------------------
# 検索結果のパース / タイトル判定
# --------------------------------------------------------------------------
HTML = '''
<a href="https://item.rakuten.co.jp/kidsroom/g73642/?scid=x" class="i">
【コンプリート】おこさまランチマスコット10 ★全5種セット</a>
<a href="https://item.rakuten.co.jp/kidsroom/gy-2608018/">
【予約】【コンプリート】サンリオキャラクターズ コインケース VOL.2 全6種セット</a>
<a href="https://item.rakuten.co.jp/othershop/zzz1/">よそのショップの商品 全5種セット</a>
<span>1,282件</span>
'''


def test_parse_results_keeps_only_target_shop():
    rows = parse_results(HTML, "kidsroom")
    assert [r["code"] for r in rows] == ["g73642", "gy-2608018"]
    assert rows[0]["url"].endswith("/g73642/")


def test_parse_total():
    assert parse_total(HTML) == 1282


@pytest.mark.parametrize("title,expected", [
    ("【コンプリート】おこさまランチマスコット10 ★全5種セット", True),
    ("モンチッチ めじるしマグカップチャーム 全5種セット コンプ", True),
    ("ガチャ 単品 ぬいぐるみ", False),
])
def test_is_complete_set(title, expected):
    assert is_complete_set(title) is expected


@pytest.mark.parametrize("title", [
    "【予約】【コンプリート】サンリオ コインケース 全6種セット",
    "サンリオ ふわわ 全5種セット 11月再入荷予約",
    "モンチッチ 全5種セット【2026年10月2次予約】",
    "パンどろぼう 全5種セット 7月→ 8月予約",
])
def test_looks_preorder(title):
    assert looks_preorder(title)


def test_normal_title_is_not_preorder():
    assert not looks_preorder("【コンプリート】おこさまランチマスコット10 ★全5種セット")


# --------------------------------------------------------------------------
# 即納判定 (配送予定)
# --------------------------------------------------------------------------
def test_shipping_date_formats_from_real_pages():
    assert extract_shipping("配送予定 8/20 9:00までの注文で最短8/23お届け") == "8/23"
    assert extract_shipping("配送予定 1～2営業日内に発送") == "1～2営業日内に発送"
    assert extract_shipping("配送予定 1〜2日以内に発送") == "1〜2日以内に発送"


def test_judge_in_stock():
    r = judge("配送予定\n8/20 9:00までの注文で最短8/23お届け\n配送情報")
    assert r["in_stock_now"] and r["reason"] == "ok"


@pytest.mark.parametrize("text", [
    "★こちらの商品は【2026年11月入荷予定の予約商品】です。",
    "発売予定：2026年8月",
    "発売予定　予約入荷待ち",
])
def test_judge_preorder_is_rejected(text):
    r = judge(f"配送予定\n{text}")
    assert not r["in_stock_now"] and r["reason"] == "preorder"


def test_judge_without_shipping_info_is_rejected():
    """発送日が読めない = 確証なし。 通さない (HQ 指示: 迷ったら落とす)."""
    r = judge("配送予定\n※お届け日は目安のため、正確な情報は注文確認画面で")
    assert not r["in_stock_now"] and r["reason"] == "no_shipping_info"


def test_availability_instock_is_not_used():
    """在庫マークだけでは通さない (予約品も InStock を返すため)."""
    r = judge("availability InStock 在庫あり")
    assert not r["in_stock_now"]


# --------------------------------------------------------------------------
# スプシ書込
# --------------------------------------------------------------------------
def test_dedupe_key_is_shop_and_code():
    assert dedupe_key("https://item.rakuten.co.jp/kidsroom/g73642/?x=1") == "kidsroom/g73642"
    assert dedupe_key("") == ""


def test_build_row_columns():
    row = build_row({"url": "https://item.rakuten.co.jp/kidsroom/g73642/",
                     "title": "【コンプリート】おこさまランチマスコット10 全5種セット",
                     "price_jpy": "2000", "image_urls": ["https://image.rakuten.co.jp/a.jpg"]})
    assert row[COL_URL - 1].endswith("/g73642/")
    assert row[COL_TITLE - 1].startswith("【コンプリート】")
    assert row[COL_CONDITION - 1] == "新品"
    assert row[COL_PRICE - 1] == "2000"
    assert row[COL_CURRENT_PRICE - 1] == "2000"   # M: 監視くんが使う列
    assert row[COL_CATEGORY - 1] == CATEGORY == "カプセルトイ"
    assert row[COL_IMAGES - 1] == "https://image.rakuten.co.jp/a.jpg"


def test_build_row_never_writes_formula_columns():
    """N (ARRAYFORMULA) と P (countif) には書かない。 貼ると HIGH が壊れる."""
    row = build_row({"url": "https://item.rakuten.co.jp/kidsroom/g1/", "title": "t",
                     "price_jpy": "1000"})
    assert row[COL_PURCHASE_PRICE - 1] == ""
    assert row[COL_CTR - 1] == ""


# --------------------------------------------------------------------------
# 2026-08-19 user 指摘: 送料込み価格で見る / 実際の食べ物は扱わない
# --------------------------------------------------------------------------
def test_free_shipping_is_the_default():
    """送料無料だけを対象にする = 表示価格がそのまま総額になる."""
    from scrapers.rakuten_search import FREE_SHIPPING_PARAM, SEARCH_URL, search_shop
    import inspect

    assert FREE_SHIPPING_PARAM == "&f=2"
    assert "{extra}" in SEARCH_URL
    assert inspect.signature(search_shop).parameters["free_shipping"].default is True


@pytest.mark.parametrize("title", [
    "サンリオ キャラクターズ ミニチュア 全5種セット",
    "おこさまランチマスコット10 全5種セット",
    "駄菓子 ミニチュア チャーム 全6種セット コンプ",
])
def test_toy_titles_pass(title):
    from scrapers.rakuten_search import is_toy
    assert is_toy(title)


@pytest.mark.parametrize("title", [
    "人気駄菓子 詰め合わせ 全5種セット",
    "訳あり お菓子 業務用 全4種",
    "チョコレート 賞味期限2026年 全5種セット",
])
def test_real_food_is_rejected(title):
    """実際の食べ物は通さない (輸出・出品の制約が別物)."""
    from scrapers.rakuten_search import is_toy
    assert not is_toy(title)


def test_toy_word_is_required_not_just_food_word_absence():
    """おもちゃ語が無ければ通さない (fail-closed)."""
    from scrapers.rakuten_search import is_toy
    assert not is_toy("サンリオ 全5種セット")


# --------------------------------------------------------------------------
# 商品画像 (2026-08-20 user 指摘「画像も取れない」)
# --------------------------------------------------------------------------
ITEM_HTML = '''
<meta property="og:image" content="https://shop.r10s.jp/auc-yuyou/cabinet/2607/g260736s02t.jpg" />
<img src="https://image.rakuten.co.jp/auc-yuyou/cabinet/parts/header/menu0.jpg">
<img src="https://image.rakuten.co.jp/auc-yuyou/cabinet/parts/side-l/bn_math.jpg">
<img src="https://tshop.r10s.jp/auc-yuyou/cabinet/2607/g260736s02t.jpg">
<img src="https://tshop.r10s.jp/auc-yuyou/cabinet/2607/g260736s02t_2.jpg">
<img src="https://tshop.r10s.jp/auc-yuyou/cabinet/2605/g26053fs01.jpg">
'''


def test_extract_images_drops_shop_banners():
    """店のヘッダ/サイドのバナーは商品写真ではない (実測 93件全部がこれだった)."""
    from scrapers.rakuten_item import extract_images
    got = extract_images(ITEM_HTML, "https://item.rakuten.co.jp/auc-yuyou/g260736s02t/")
    assert all("parts/" not in u for u in got)
    assert got[0].endswith("/g260736s02t.jpg")
    # 商品コードを含む別カットは拾う / 他商品 (g26053fs01) は拾わない
    assert any(u.endswith("g260736s02t_2.jpg") for u in got)
    assert not any("g26053fs01" in u for u in got)


def test_extract_images_dedupes_shop_and_tshop():
    from scrapers.rakuten_item import extract_images
    got = extract_images(ITEM_HTML, "https://item.rakuten.co.jp/auc-yuyou/g260736s02t/")
    names = [u.rsplit("/", 1)[-1] for u in got]
    assert len(names) == len(set(names))


def test_extract_images_returns_empty_when_nothing_certain():
    """og:image も 商品コード付き画像も無ければ 空 (バナーで埋めない)."""
    from scrapers.rakuten_item import extract_images
    html = '<img src="https://image.rakuten.co.jp/mirakikaku/cabinet/rkanban.jpg">'
    assert extract_images(html, "https://item.rakuten.co.jp/mirakikaku/2608001/") == []


# --------------------------------------------------------------------------
# 商品説明 / JAN / メーカー欄 (2026-08-20)
# --------------------------------------------------------------------------
DESC_HTML = '''
<meta itemprop="gtin13" content="4573611790708">
<td class="item_desc"><b>アイマイナ めじるしマスコット</b><br>
メーカー：フクヤ<br>ラインナップ 1.ノーマル 2.神っぽいな<br>■サイズ：約14.0cm
&#9758;&emsp;この商品のセット、単品一覧を見る</td>
'''


def test_extract_description_keeps_lineup_and_drops_related_links():
    from scrapers.rakuten_item import extract_description
    d = extract_description(DESC_HTML)
    assert "ラインナップ" in d and "約14.0cm" in d
    assert "この商品のセット" not in d      # 末尾の関連商品リンクは落とす
    assert "<" not in d                     # タグは残さない


def test_extract_jan():
    from scrapers.rakuten_item import extract_jan
    assert extract_jan(DESC_HTML) == "4573611790708"
    assert extract_jan("<html></html>") == ""


def test_maker_from_description_covers_shops_without_maker_in_title():
    """mirakikaku 等 タイトルにメーカーが入らない店は 説明の メーカー欄 で拾う."""
    from gacha_maker import official_url
    from scrapers.rakuten_item import extract_description
    d = extract_description(DESC_HTML)
    assert official_url("アイマイナ めじるしマスコット 全5種セット", d).startswith(
        "https://www.fancy-fukuya.co.jp/")


def test_unknown_maker_in_description_is_still_blank():
    from gacha_maker import official_url
    assert official_url("どうぶつの森 全8種セット", "メーカー：日本オート玩具 ラインナップ") == ""


def test_shipping_without_leading_date():
    """「13:00までの注文で最短8/22お届け」= 頭の日付が出ない表示 (2026-08-20 実測).

    日付必須にしていたため auc-yuyou が丸ごと no_shipping_info で落ちていた。
    """
    from scrapers.rakuten_item import extract_shipping, judge
    t = "配送予定 13:00までの注文で最短8/22お届け ※お届け日は目安のため"
    assert extract_shipping(t) == "8/22"
    assert judge(t)["in_stock_now"] is True


# --------------------------------------------------------------------------
# 送料 (2026-08-20 user 指示: 送料無料縛りをやめて 価格+送料 で見る)
# --------------------------------------------------------------------------
@pytest.mark.parametrize("text,fee", [
    ("配送情報 送料680円 宅配便[特定送料] 送料無料ライン対象外 6,500円以上で送料無料", 680),
    ("配送情報 送料330円 追跡可能メール便[特定送料](ヤマト運輸) 送料無料ライン対象外", 330),
    ("配送情報 送料無料 宅配便(佐川急便) 送料無料ライン対象", 0),
    # 読めない = None。 「6,500円以上で送料無料」を送料と誤読しない
    ("配送情報 追跡可能メール便 ※離島･一部地域は追加送料がかかる場合があります。", None),
    ("在庫について", None),
])
def test_extract_shipping_fee(text, fee):
    from scrapers.rakuten_item import extract_shipping_fee
    assert extract_shipping_fee(text) == fee


def test_build_row_puts_total_in_m_and_breakdown_in_h():
    from sheet_writer_rakuten import COL_CURRENT_PRICE, COL_DESCRIPTION, build_row
    row = build_row({"url": "https://item.rakuten.co.jp/auc-toysanta/x1/",
                     "title": "テスト 全5種セット", "price_jpy": "2820",
                     "shipping_fee": 680, "total_jpy": "3500", "description": "説明"})
    assert row[COL_CURRENT_PRICE - 1] == "3500"          # M = 送料込み総額
    assert "本体2820円 + 送料680円 = 3500円" in row[COL_DESCRIPTION - 1]


@pytest.mark.parametrize("title,out", [
    ("【品切中】【送料無料】【全部揃ってます!!】葬送のフリーレン [全25種セット]", True),
    ("【送料無料】【全部揃ってます!!】カービィのエアライダー [全20種セット]", False),
])
def test_looks_soldout(title, out):
    from scrapers.rakuten_search import looks_soldout
    assert looks_soldout(title) is out


def test_fetch_detail_rejects_redirect_to_shop_top():
    """消えた商品は店トップへ飛ばされる。 その文言を商品情報として拾わない."""
    from scrapers import rakuten_item

    class _Dead:
        current_url = "https://www.rakuten.co.jp/jugem2020/"
        def get(self, url): pass
        def find_element(self, *a): raise AssertionError("本文を読んではいけない")

    assert rakuten_item.fetch_detail(_Dead(), "https://item.rakuten.co.jp/jugem2020/x1/",
                                     wait_sec=0) is None
