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
