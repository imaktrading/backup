"""tests/test_rakuten_gacha - 楽天ガチャポン収集の判定ロジック.

2026-08-19 新設。 実測 (POC) で分かった事をテストに固定する:
  - 在庫マーク (availability) は使えない。 予約品も InStock を返す
  - 即納の判定は **配送予定に発送日があるか**。 無ければ通さない (fail-closed)
  - HIGH の N/P は数式なので **中間スプシでも N/P には書かない**
"""
from __future__ import annotations

import pytest

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
# 即納判定 — **共有の条件表だけ** を使う (2026-08-22 窓口回答)
#   `2026-08-19_inventory_rakuten_delivery_static_response`
#   自前の正規表現 (画面テキストの「最短8/22お届け」等) は捨てた。 残しておくと
#   HTTP が取れなかった時に そちらだけで即納と判定でき、 共有表を迂回する
# --------------------------------------------------------------------------
def test_self_written_shipping_regex_is_gone():
    """判定口は1つ。 `judge` / `extract_shipping` を復活させない."""
    from scrapers import rakuten_item
    assert not hasattr(rakuten_item, "judge")
    assert not hasattr(rakuten_item, "extract_shipping")
    assert not hasattr(rakuten_item, "SHIP_DATE_RE")


class _Driver:
    """`fetch_detail` に渡す最小のドライバ (ブラウザは開かない)."""

    def __init__(self, html: str, text: str = "配送情報 送料無料"):
        self.page_source = html
        self._text = text
        self.current_url = ""

    def get(self, url):
        self.current_url = url

    def find_element(self, *a):
        return type("E", (), {"text": self._text})()


def _page(msg: str, category: str = "553785", name: str = "ガチャガチャ") -> str:
    """商品ページの HTML (要る所だけ). 改行は実物どおり ld+json の中に入れる."""
    crumb = ('{"item": {"@id": "https://www.rakuten.co.jp/category/CID/"\n'
             '   ,"name": "NAME"}}')
    crumbs = (crumb.replace("CID", "101164").replace("NAME", "ホビー") + "\n ,"
              + crumb.replace("CID", category).replace("NAME", name))
    return ('<script type="application/ld+json">\n {"@type": "BreadcrumbList"\n'
            f' ,"itemListElement": [{crumbs}]}}\n</script>'
            'itemprop="availability" content="InStock"'
            'itemprop="price" content="2820"'
            f'"deliveryMessage":"{msg}"')


_VERDICT_TO_REASON = {"immediate": ("ok", True),
                      "preorder": ("preorder", False),
                      "skip": ("no_shipping_info", False)}


def _cases():
    """ケースは **共有の条件表から読む** (窓口 回答の指示)."""
    from rakuten_delivery import load_rule
    return [(c["msg"], c["expect"]) for c in load_rule()["cases"]]


@pytest.mark.parametrize("msg,expect", _cases())
def test_fetch_detail_judges_only_by_the_shared_table(msg, expect):
    """ブラウザ経由でも 判定は共有表と同じ結果になる."""
    from scrapers import rakuten_item
    reason, in_stock = _VERDICT_TO_REASON[expect]
    d = _Driver(_page(msg))
    res = rakuten_item.fetch_detail(d, "https://item.rakuten.co.jp/auc-yuyou/x1/", wait_sec=0)
    assert res["in_stock_now"] is in_stock and res["reason"] == reason


@pytest.mark.parametrize("msg", [
    # 以前 **自前の正規表現が即納として拾っていた** 書き方。
    # 今は共有表の答えに従う (表が後で直っても このテストは追従する)
    "13:00までの注文で最短8/22お届け",
    "即納｜営業日14時までのご注文で当日出荷",   # auc-toysanta 実測 2026-08-22 (30/30件)
    "翻営業日までに発送",
])
def test_store_specific_wording_follows_the_table_not_our_own_regex(msg):
    from rakuten_delivery import judge_message
    from scrapers import rakuten_item
    reason, in_stock = _VERDICT_TO_REASON[judge_message(msg)]
    d = _Driver(_page(msg))
    res = rakuten_item.fetch_detail(d, "https://item.rakuten.co.jp/auc-yuyou/x1/", wait_sec=0)
    assert res["in_stock_now"] is in_stock and res["reason"] == reason


def test_availability_instock_is_not_used():
    """在庫マークだけでは通さない (予約品も InStock を返すため)."""
    from scrapers import rakuten_item
    d = _Driver(_page("2026年10月発売予定"))
    res = rakuten_item.fetch_detail(d, "https://item.rakuten.co.jp/auc-yuyou/x1/", wait_sec=0)
    assert res["in_stock_now"] is False


# --------------------------------------------------------------------------
# パンくず「ガチャガチャ」 — 拾う条件のもう片方 (2026-08-22 窓口回答)
#   `2026-08-19_gacha_implement_go_response`
# 実測 2026-08-22 (5店40件): ガチャガチャ = カテゴリ id 553785
# --------------------------------------------------------------------------
def test_breadcrumb_is_parsed():
    from scrapers.rakuten_item import parse_breadcrumb
    assert parse_breadcrumb(_page("1〜2営業日内に発送")) == [
        ("101164", "ホビー"), ("553785", "ガチャガチャ")]


@pytest.mark.parametrize("category,name,ok", [
    ("553785", "ガチャガチャ", True),
    ("406810", "食玩・おまけ", False),      # ガチャガチャでない楽天カテゴリの例
    ("112203", "フィギュア", False),
])
def test_gacha_category_gate(category, name, ok):
    from scrapers.rakuten_item import is_gacha_category
    assert is_gacha_category(_page("1〜2営業日内に発送", category, name)) is ok


def test_gacha_category_is_false_when_breadcrumb_missing():
    """読めない物を通さない (fail-closed)."""
    from scrapers.rakuten_item import is_gacha_category
    assert is_gacha_category('"deliveryMessage":"1〜2営業日内に発送"') is False
    assert is_gacha_category("") is False


def test_parse_detail_html_exposes_the_gate():
    from scrapers.rakuten_item import parse_detail_html
    d = parse_detail_html(_page("1〜2営業日内に発送"), "https://item.rakuten.co.jp/a/b/")
    assert d["is_gacha_category"] is True
    assert d["breadcrumb"] == ["ホビー", "ガチャガチャ"]


@pytest.mark.parametrize("category,msg,ok,why", [
    ("553785", "1〜2営業日内に発送", True, "ok"),
    # ★条件は **両方**。 即納でもカテゴリが違えば採らない
    ("406810", "1〜2営業日内に発送", False, "not_gacha_category"),
    ("553785", "2026年10月発売予定", False, "preorder"),
    ("553785", "", False, "skip"),
])
def test_detail_verdict_needs_both_conditions(category, msg, ok, why):
    from run_harvest_rakuten_gacha import detail_verdict
    from scrapers.rakuten_item import parse_detail_html
    pre = parse_detail_html(_page(msg, category, "x"), "https://item.rakuten.co.jp/a/b/")
    assert detail_verdict(pre) == (ok, why)


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
    assert row[COL_CURRENT_PRICE - 1] == ""       # M には書かない (仕入値は F のみ)
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


def test_toy_word_is_no_longer_required():
    """★2026-08-21 方針変更: おもちゃ語の白リストはやめた。

    白リスト方式は **菓子と無関係のただの玩具を大量に落としていた**
    (実測 auc-toysanta 180件中91件が not_toy、うち約60件が玩具)。
    `is_toy` を呼ぶ前に `is_complete_set` (= ガチャのコンプ品) が通っているので、
    見るべきは「食べ物が入っているか」だけ。
    """
    from scrapers.rakuten_search import is_toy
    assert is_toy("サンリオ 全5種セット")
    assert not is_toy("サンリオ 全5種セット お菓子 詰め合わせ")


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


def test_build_row_puts_total_in_f_and_breakdown_in_h():
    """★仕入値は **F列だけ**。M には書かない (2026-09-08 user 確定: HIGH が壊れるため)."""
    from sheet_writer_rakuten import (COL_CURRENT_PRICE, COL_DESCRIPTION,
                                      COL_PRICE, build_row)
    row = build_row({"url": "https://item.rakuten.co.jp/auc-toysanta/x1/",
                     "title": "テスト 全5種セット", "price_jpy": "2820",
                     "shipping_fee": 680, "total_jpy": "3500", "description": "説明"})
    assert row[COL_PRICE - 1] == "3500"                  # F = 送料込み総額
    assert row[COL_CURRENT_PRICE - 1] == ""              # M は空
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


# --------------------------------------------------------------------------
# 検索語の組み立て (2026-08-21 user 確定: メーカー名で引く)
# --------------------------------------------------------------------------
def test_query_is_built_per_shop():
    from run_harvest_rakuten_gacha import query_for
    assert query_for("auc-yuyou", "バンダイ") == "バンダイ コンプリート"
    assert query_for("mirakikaku", "バンダイ") == "バンダイ コンプリート"
    # トイサンタだけ言い回しが違う
    assert query_for("auc-toysanta", "バンダイ") == "バンダイ 全部揃ってます"


def test_makers_cover_the_five_allowed():
    from gacha_maker import ALLOWED_MAKERS
    from run_harvest_rakuten_gacha import MAKERS
    assert {label for label, _, _ in MAKERS} == set(ALLOWED_MAKERS)
    # ブシロードは正式名では検索できない (タイトルは「ブシロード」)
    assert dict((l, w) for l, w, _ in MAKERS)["ブシロードクリエイティブ"] == "ブシロード"


def test_shop_of_and_tab_name():
    """タブは **店ごと** (user 確定 2026-08-21)。 送料や仕入条件が店単位で違うため."""
    from sheet_writer_rakuten import build_tab_name, shop_of
    u = "https://item.rakuten.co.jp/auc-toysanta/abc123/"
    assert shop_of(u) == "auc-toysanta"
    assert build_tab_name(shop_of(u)) == "rakuten_auc_toysanta"
    assert shop_of("https://example.com/x") == ""


# --------------------------------------------------------------------------
# 食べ物の扱い (2026-08-21 改訂)
# --------------------------------------------------------------------------
@pytest.mark.parametrize("title,keep", [
    # お菓子の **ミニチュア** は玩具 (user 確定 2026-08-19)
    ("ぷるんと蒟蒻ゼリー ミニチュアチャーム 全5種セット", True),
    ("つぶグミ ミニチュアチャーム 全7種セット", True),
    # おもちゃ語が無くても、 コンプ品と分かっていれば通す (2026-08-21 改訂)
    ("溶けてる！猫ちゃあぁぁん [全5種セット(フルコンプ)]", True),
    ("ちいかわ きゃらまかろん(再販) [全4種セット(フルコンプ)]", True),
    ("Capsule Flockies パペットスンスン [全4種セット(フルコンプ)]", True),
    # 実際にお菓子が入っている物は落とす (テンプレ対応まで)
    ("おぱんちゅうさぎとわんころマスコット ビスケットつき 全10種セット", False),
    ("ワンピース大海賊シールウエハースLOG.15 全38種セット", False),
    ("ズートピア カードソフトクッキー 全33種セット", False),
    # 実食品そのもの
    ("お菓子 詰め合わせ 業務用 全5種", False),
    ("駄菓子 内容量 500g 全5種", False),
])
def test_is_toy_blocks_only_real_food(title, keep):
    from scrapers.rakuten_search import is_toy
    assert is_toy(title) is keep


def test_is_snack_toy_marks_candy_included():
    """テンプレに「お菓子は付けません」が入ったら通す候補を数えられるようにする."""
    from scrapers.rakuten_search import is_snack_toy
    assert is_snack_toy("ワンピース大海賊シールウエハース 全38種セット") is True
    assert is_snack_toy("ぷるんと蒟蒻ゼリー ミニチュアチャーム 全5種セット") is False


# --------------------------------------------------------------------------
# 台紙あり/なしの重複 (HQ 依頼 2026-08-20)
# --------------------------------------------------------------------------
def test_base_title_key_treats_board_variants_as_same():
    from sheet_writer_rakuten import base_title_key, has_board
    a = "ちいさな アニマル スツール 2 全5種セット：遊you 楽天市場店"
    b = "ちいさな アニマル スツール 2 全5種+ディスプレイ台紙セット：遊you 楽天市場店"
    assert base_title_key(a) == base_title_key(b)
    assert has_board(b) and not has_board(a)


def test_base_title_key_keeps_different_products_apart():
    from sheet_writer_rakuten import base_title_key
    assert base_title_key("A 全5種セット") != base_title_key("B 全5種セット")
    # 弾違いは別物
    assert base_title_key("めじるし 2 全5種セット") != base_title_key("めじるし 3 全5種セット")


def test_k_column_point_is_left_empty():
    """K列 (ポイント) は **空**で確定 (窓口 回答 `2026-08-19_gacha_implement_go_response`).

    確定値が静的HTMLに無いので推測で入れない。 ポイントのために Selenium は足さない。
    """
    from sheet_writer_rakuten import build_row
    row = build_row({"url": "https://item.rakuten.co.jp/auc-yuyou/x1/",
                     "title": "テスト 全5種セット", "price_jpy": "2820",
                     "shipping_fee": 0, "total_jpy": "2820"})
    assert row[11 - 1] == ""


# --------------------------------------------------------------------------
# 食玩 (お菓子付き) — 2026-08-23
#   窓口 回答 `2026-08-22_hq_gacha_foodtoy_column_response` の3点:
#     ① パンくずの許可を **auc-toysanta に限り**「ガチャガチャ または 食玩・おまけ」に
#     ② S列に `■分類：` から `食玩` / 空欄。 それ以外と 欄が無い物は採らない
#     ③ 枠は auc-toysanta 10件から
#   実測 (2026-08-23 実サイト HTTP 取得):
#     食玩 bs-5l8y0019a7-011 → パンくず 406810 食玩・おまけ / `■分類：食玩`
#     ガチャ g-5l90001975-007 → 553785 ガチャガチャ / `■分類：ガチャガチャ`
#     BOX  b-5l660018zm-009  → 112203 フィギュア     / `■分類：BOXフィギュア`
# --------------------------------------------------------------------------
_TOYSANTA = "https://item.rakuten.co.jp/auc-toysanta/bs-1/"
_YUYOU = "https://item.rakuten.co.jp/auc-yuyou/x1/"


def test_foodtoy_breadcrumb_is_recognised():
    from scrapers.rakuten_item import is_foodtoy_category, is_gacha_category
    html = _page("1〜2営業日内に発送", "406810", "食玩・おまけ")
    assert is_foodtoy_category(html) is True
    assert is_gacha_category(html) is False        # ガチャガチャ判定は据え置き


@pytest.mark.parametrize("category,name,url,ok", [
    # ガチャガチャは全店
    ("553785", "ガチャガチャ", _TOYSANTA, True),
    ("553785", "ガチャガチャ", _YUYOU, True),
    # 食玩・おまけ は auc-toysanta だけ
    ("406810", "食玩・おまけ", _TOYSANTA, True),
    ("406810", "食玩・おまけ", _YUYOU, False),
    # どちらでもない区分は どの店でも採らない
    ("112203", "フィギュア", _TOYSANTA, False),
])
def test_foodtoy_breadcrumb_is_allowed_only_for_toysanta(category, name, url, ok):
    from scrapers.rakuten_item import is_collectable_category
    assert is_collectable_category(_page("1〜2営業日内に発送", category, name), url) is ok


def test_collectable_category_is_false_when_breadcrumb_missing():
    """読めなければ通さない (fail-closed)."""
    from scrapers.rakuten_item import is_collectable_category
    assert is_collectable_category("", _TOYSANTA) is False


@pytest.mark.parametrize("desc,url,ok,mark,why", [
    ("■分類：食玩 ■メーカー：バンダイ", _TOYSANTA, True, "食玩", "ok"),
    ("■分類：ガチャガチャ ■メーカー：バンダイ", _TOYSANTA, True, "", "ok"),
    # それ以外の値は採らない
    ("■分類：BOXフィギュア", _TOYSANTA, False, "", "class_ng"),
    # 欄を書く店で 欄が無ければ採らない
    ("メーカー：バンダイ", _TOYSANTA, False, "", "class_missing"),
    # 欄そのものが無い店は 今までどおり (S列は空欄)
    ("メーカー：バンダイ", _YUYOU, True, "", "ok"),
])
def test_classify_food_toy(desc, url, ok, mark, why):
    from scrapers.rakuten_item import classify_food_toy
    assert classify_food_toy(desc, url) == (ok, mark, why)


def test_food_toy_is_never_guessed_from_title():
    """タイトルの「チョコ」等では 食玩にしない (キャラ名にも出るので必ず誤判定する)."""
    from scrapers.rakuten_item import classify_food_toy
    ok, mark, _why = classify_food_toy(
        "■分類：ガチャガチャ チョコレートマスコット 全5種セット", _TOYSANTA)
    assert (ok, mark) == (True, "")


def test_parse_detail_html_exposes_food_toy_gate():
    from scrapers.rakuten_item import parse_detail_html
    d = parse_detail_html(
        _page("1〜2営業日内に発送", "406810", "食玩・おまけ")
        + '<td class="item_desc">■分類：食玩 ■メーカー：バンダイ</td>', _TOYSANTA)
    assert d["is_collectable_category"] is True
    assert d["is_foodtoy_category"] is True
    assert d["item_class"] == "食玩"


@pytest.mark.parametrize("category,name,desc,url,ok,why", [
    ("406810", "食玩・おまけ", "■分類：食玩", _TOYSANTA, True, "ok"),
    ("406810", "食玩・おまけ", "■分類：食玩", _YUYOU, False, "not_gacha_category"),
    ("553785", "ガチャガチャ", "■分類：BOXフィギュア", _TOYSANTA, False, "class_ng"),
    ("553785", "ガチャガチャ", "メーカー：バンダイ", _TOYSANTA, False, "class_missing"),
    ("553785", "ガチャガチャ", "メーカー：バンダイ", _YUYOU, True, "ok"),
])
def test_detail_verdict_covers_food_toy(category, name, desc, url, ok, why):
    from run_harvest_rakuten_gacha import detail_verdict
    from scrapers.rakuten_item import parse_detail_html
    pre = parse_detail_html(
        _page("1〜2営業日内に発送", category, name)
        + f'<td class="item_desc">{desc}</td>', url)
    assert detail_verdict(pre) == (ok, why)


def test_build_row_writes_s_column():
    """S列 = 出品くん `gacha_to_csv.py` の FOOD_TOY_COL(18, 0起点) が読む列."""
    from sheet_writer_rakuten import COL_FOOD_TOY, build_row
    assert COL_FOOD_TOY == 19
    base = {"url": _TOYSANTA, "title": "テスト 全5種セット", "price_jpy": "2820",
            "shipping_fee": 0, "total_jpy": "2820"}
    assert build_row({**base, "food_toy": "食玩"})[COL_FOOD_TOY - 1] == "食玩"
    assert build_row({**base, "food_toy": ""})[COL_FOOD_TOY - 1] == ""
    assert build_row(base)[COL_FOOD_TOY - 1] == ""     # 印が無ければ空欄 = 通常


def test_food_toy_quota_defaults_to_ten():
    """食玩は対象年齢が全件目視。 枠は 10件から (窓口 回答 ③)."""
    from run_harvest_rakuten_gacha import FOODTOY_QUOTA, foodtoy_over_quota
    assert FOODTOY_QUOTA == 10
    assert foodtoy_over_quota("食玩", 9, 10) is False
    assert foodtoy_over_quota("食玩", 10, 10) is True
    # 通常のカプセルトイは 食玩の枠に食われない
    assert foodtoy_over_quota("", 999, 10) is False


def test_price_column_f_holds_the_shipping_included_total():
    """★F列 = 仕入原価 (本体+送料) (2026-09-05 user 確定「中間スプシの価格はF列で」).

    本体だけを入れると、送料が乗る店 (トイサンタは約9割が有料) で仕入原価を誤る。
    """
    from sheet_writer_rakuten import COL_CURRENT_PRICE, COL_PRICE, build_row
    row = build_row({"url": "https://item.rakuten.co.jp/auc-toysanta/x1/",
                     "title": "テスト 全5種セット", "price_jpy": "2500",
                     "shipping_fee": 680, "total_jpy": "3180"})
    assert row[COL_PRICE - 1] == "3180"
    # ★M列には書かない (2026-09-08 user 確定「仕入値は F のみ」)
    assert row[COL_CURRENT_PRICE - 1] == ""
    # 送料無料なら本体がそのまま総額
    free = build_row({"url": "https://item.rakuten.co.jp/mirakikaku/x2/",
                      "title": "テスト 全5種セット", "price_jpy": "1980",
                      "shipping_fee": 0, "total_jpy": "1980"})
    assert free[COL_PRICE - 1] == "1980"
