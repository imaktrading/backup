"""yodobashi_search_http のオフラインテスト (= 保存 HTML / 純粋関数)."""
import pytest

from scrapers.yodobashi_search_http import (
    build_page_url,
    extract_clean_title,
    extract_detail_images,
    extract_model_from_title,
    extract_points_jpy,
    extract_point_rate,
    is_in_stock,
    parse_product_tiles,
)

BASE = ("https://www.yodobashi.com/category/18457/18458/m0000008179/"
        "?spcs=Specvaluecode_x&word=G-shock")


def test_build_page_url_page1_unchanged():
    assert build_page_url(BASE, 1) == BASE


def test_build_page_url_inserts_pN():
    u = build_page_url(BASE, 2)
    assert "/m0000008179/p2/?" in u
    assert "word=G-shock" in u


@pytest.mark.parametrize("title,expected", [
    ("カシオ CASIO G-SHOCK ジーショック DW-5000R-1AJF", "DW-5000R-1AJF"),
    ("カシオ G-SHOCK LOV-25A-7AJR ペアウォッチ", "LOV-25A-7AJR"),
    ("カシオ G-SHOCK GA-2100-1A1JF ブラック", "GA-2100-1A1JF"),
    # JIS(JF/JR) が無ければ汎用 model に fallback
    ("カシオ G-SHOCK GW-B5600 シリーズ", "GW-B5600"),
    ("型番なしタイトル", ""),
])
def test_extract_model(title, expected):
    assert extract_model_from_title(title) == expected


@pytest.mark.parametrize("text,expected", [
    ("明後日中にお届けできます カシオ G-SHOCK DW-5000R", True),
    ("3日後にお届けできます カシオ G-SHOCK GW-8202K", True),
    ("在庫あり カシオ G-SHOCK", True),
    # skip 系 (取寄/廃番/予約)
    ("ご注文後、出荷日をご連絡します カシオ G-SHOCK", False),
    ("予定数の販売を終了しました カシオ G-SHOCK", False),
    ("ご予約受付中 カシオ G-SHOCK", False),
    ("", False),
])
def test_is_in_stock(text, expected):
    assert is_in_stock(text) is expected


def test_is_in_stock_out_marker_wins_over_delivery():
    # 「お取り寄せ」表記があれば お届け表記より優先で skip (fail-closed)
    assert is_in_stock("お取り寄せ 明後日中にお届けできます") is False


# --- detail page 抽出 (= 実 markup を模した snippet) ---
_DETAIL = (
    '<meta name="description" content="カシオ CASIO G-SHOCK ジーショック AW-591-2AJF'
    'の通販ならヨドバシカメラの公式サイト">'
    '<span id="js_scl_pointValue" class="orange">1,066</span>'
    '<span id="js_scl_pointrate">（10％還元）</span>'
    '<span id="js_scl_pointPrice">（￥1,066相当）</span>'
    '<img src="https://image.yodobashi.com//product/100/000/001/000/893/847/'
    '100000001000893847_10203_004.jpg">'
    '<img src="https://image.yodobashi.com//product/100/000/001/000/893/847/'
    '100000001000893847_10201.jpg">'
    # おすすめ商品の別 pid 画像 (= 除外されるべき)
    '<img src="https://image.yodobashi.com//product/999/000/000/000/000/000/'
    '999000000000000000_10203.jpg">'
)


def test_extract_points_jpy_direct_value():
    # 直値 1,066 を採る (率×価格の計算ではなく pointValue 直読み)
    assert extract_points_jpy(_DETAIL) == 1066


def test_extract_points_jpy_none_when_absent():
    assert extract_points_jpy("<div>no points here</div>") is None


def test_extract_point_rate():
    assert extract_point_rate(_DETAIL) == 10


def test_extract_detail_images_scoped_and_normalized():
    imgs = extract_detail_images(_DETAIL, "100000001000893847")
    # 自 pid の 2 枚のみ (999 の別商品画像は除外)、 // が / に正規化
    assert len(imgs) == 2
    assert all("/product/" in u and "//product" not in u for u in imgs)
    assert all("100000001000893847_" in u for u in imgs)


def test_extract_detail_images_limit():
    pid = "100000001000893847"
    many = "".join(
        f'<img src="https://image.yodobashi.com//product/1/0/0/0/0/0/{pid}_{i:05d}.jpg">'
        for i in range(20)
    )
    assert len(extract_detail_images(many, pid, limit=8)) == 8


def test_extract_clean_title_strips_boilerplate():
    t = extract_clean_title(_DETAIL)
    assert "AW-591-2AJF" in t
    assert "通販" not in t  # 「の通販なら…」以降は落とす


def test_parse_product_tiles_container_scoped():
    """js_productList 外 (おすすめ等) は拾わない。"""
    html = """
    <div class="recommend"><a href="/product/999/">おすすめ電池</a></div>
    <div class="js_productList">
      <div class="productListTile">
        <a href="/product/100000001000893847/">x</a>
        明後日中にお届けできます カシオ CASIO G-SHOCK ジーショック DW-5000R-1AJF ¥26,100
      </div>
      <div class="productListTile">
        <a href="/product/100000001001146484/">y</a>
        予定数の販売を終了しました カシオ G-SHOCK GA-B2100KB-2AJR ¥29,150
      </div>
    </div>
    """
    tiles = parse_product_tiles(html)
    assert len(tiles) == 2  # recommend の 999 は含まない
    a, b = tiles
    assert a["product_id"] == "100000001000893847"
    assert a["model_number"] == "DW-5000R-1AJF"
    assert a["price_jpy"] == 26100
    assert a["in_stock"] is True
    assert a["is_gshock"] is True
    assert b["in_stock"] is False  # 販売終了 → skip 対象
