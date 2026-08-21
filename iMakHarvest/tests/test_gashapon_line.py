"""tests/test_gashapon_line - 公式の商品ラインを起点に仕入元を探す (2026-08-21 新設).

店を先に決める探し方では集まらない商品ライン (めじるしアクセサリー: 公式84商品が
楽天の12店にばらけ、1店あたり数商品) 向け。
"""
from __future__ import annotations

import pytest

from run_harvest_gashapon_line import official_products, title_matches

pytestmark = pytest.mark.offline


def test_title_matches_requires_full_official_name():
    o = "TOY STORY5 めじるしアクセサリー"
    assert title_matches(o, "【全5種コンプリートセット】TOY STORY5 めじるしアクセサリー バンダイ")
    # 記号・空白の差は吸収する
    assert title_matches(o, "TOY　STORY5めじるしアクセサリー 全5種セット")


def test_title_matches_rejects_other_products_in_the_same_series():
    """同じシリーズの別弾を掴まない (fail-closed)."""
    assert not title_matches("ドラゴンボール めじるしアクセサリー4",
                             "ドラゴンボール めじるしアクセサリー3 全5種セット")
    assert not title_matches("サマーウォーズ めじるしアクセサリー2",
                             "サマーウォーズ めじるしアクセサリー 全5種セット")


def test_title_matches_rejects_short_names():
    """短すぎる名前は誤爆するので通さない."""
    assert not title_matches("くじ", "ガシャポンくじ 全5種セット")


def test_official_products_filters_by_line(monkeypatch):
    import gacha_age
    monkeypatch.setattr(gacha_age, "fetch_catalog", lambda *a, **k: [
        ("x", "1111111111111000", "TOY STORY5 めじるしアクセサリー"),
        ("y", "2222222222222000", "ドラゴンボール カプセルフィギュア"),
    ])
    got = official_products("めじるし")
    assert got == [("TOY STORY5 めじるしアクセサリー", "1111111111111000")]


# --------------------------------------------------------------------------
# 出せない区分 / 公式の商品ページ・画像 (HQ 依頼 2026-08-20)
# --------------------------------------------------------------------------
@pytest.mark.parametrize("title,ng", [
    ("サンリオ キャラクターズ ミニチュア 全5種セット", True),        # user 判断で扱わない
    ("ハローキティ フィギュア 全5種セット", True),
    ("ちいかわ ぬいぐるみ ポーチ 全4種セット", True),                # CPSC: 児童製品確定
    ("もふもふ アニマル マスコット 全5種セット", True),
    ("ドラゴンボール めじるしアクセサリー4 全5種セット", False),
    ("あそべる生物 フィギュア 昆虫の森 全4種セット", False),
])
def test_excluded_category(title, ng):
    from scrapers.rakuten_search import is_excluded_category
    assert is_excluded_category(title) is ng


OFFICIAL_HTML = '''
<img src="https://bandai-a.akamaihd.net/bc/img/model/xl/1000255261_1.jpg">
<img src="https://bandai-a.akamaihd.net/bc/img/model/xl/1000255261_2.jpg">
<img src="https://gashapon.jp/images/common/bnr_gashapondoko.png">
<img src="https://bandai-a.akamaihd.net/bc/img/model/xl/9999999999_1.jpg">
<dt>対象年齢</dt><dd>15才以上</dd>
'''


def test_parse_official_images_keeps_only_this_product():
    """公式ページには関連商品の写真も並ぶ。 1枚目と同じ model の物だけ採る."""
    from gacha_age import parse_official_images
    got = parse_official_images(OFFICIAL_HTML)
    assert got == ["https://bandai-a.akamaihd.net/bc/img/model/xl/1000255261_1.jpg",
                   "https://bandai-a.akamaihd.net/bc/img/model/xl/1000255261_2.jpg"]


def test_official_page_url_is_a_product_page():
    """トップページは入れない (HQ 指摘 2026-08-20)."""
    from gacha_age import product_page_url
    u = product_page_url("4570118196569000")
    assert u.startswith("https://gashapon.jp/products/detail.php?jan_code=")
    assert product_page_url("") == ""


def test_official_columns_are_v_and_w():
    """列位置は HQ に伝える約束。 変えたら知らせること."""
    from sheet_writer_rakuten import COL_OFFICIAL_IMAGES, COL_OFFICIAL_PAGE
    assert (COL_OFFICIAL_PAGE, COL_OFFICIAL_IMAGES) == (22, 23)   # V, W


def test_i_column_is_left_for_hq():
    """I列は出品くんの英語タイトル列。 こちらは書かない."""
    from sheet_writer_rakuten import build_row
    row = build_row({"url": "https://item.rakuten.co.jp/x/y/", "title": "t 全5種",
                     "price_jpy": "100", "official_page": "https://gashapon.jp/x"})
    assert row[8] == ""
