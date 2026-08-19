"""tests/test_gacha_maker - ガチャのタイトルから メーカー公式URL を引く.

2026-08-20 新設 (user 依頼: I列に公式URL)。 実測で固定すること:
  - メーカー名は 「…セット <メーカー> ガチャポン…」 のスロットにしか無い
    (楽天の商品ページには メーカー欄が無い / 全文検索は同店の「おすすめ商品」を誤検出)
  - 表に無いメーカー・スロット無しは **空欄** (推測で URL を入れない)
"""
from __future__ import annotations

import pytest

from gacha_maker import MAKER_OFFICIAL, extract_maker_text, official_url, resolve_maker
from sheet_writer_rakuten import COL_OFFICIAL_URL, build_row

pytestmark = pytest.mark.offline


# 実際に収集した 93件から採った生タイトル
@pytest.mark.parametrize("title,maker", [
    ("サンリオ ハローキティ スタイルアップ フィギュア コレクション 全4種+ディスプレイ台紙セット"
     " タカラトミーアーツ ガチャポン ガチャガチャ コンプリート", "タカラトミーアーツ"),
    ("超リアル ミニチュア 駄菓子 マスコット 12 全5種+ディスプレイ台紙セット"
     " トイズスピリッツ ガチャポン ガチャガチャ ガシャポン コンプリート", "トイズスピリッツ"),
    ("ふわふわ ミニ 菓子パン マスコット 3 全5種+ディスプレイ台紙セット"
     " J.DREAM ガチャポン ガチャガチャ コンプリート", "Jドリーム"),
    ("虚無 KYOMU 全5種+ディスプレイ台紙セット エール ガチャポン ガチャガチャ コンプリート", "エール"),
    ("もんとみ アニマルアトラクション もっちり アニマルの チューリップ めじるし マスコット"
     " 全5種セット スタンドストーンズ ガチャポン ガチャガチャ コンプリート", "スタンド・ストーンズ"),
    ("サンリオ キャラクターズ シャカシャカ フレーク シール風 チャーム 全10種セット"
     " ベネリック ガチャポン ガチャガチャ コンプリート", "ベネリック"),
])
def test_maker_from_title_slot(title, maker):
    assert resolve_maker(title) == maker
    assert official_url(title) == MAKER_OFFICIAL[maker]


def test_unknown_maker_is_blank_not_guessed():
    """表に無いメーカー (公式サイトが無い夢屋 等) は空欄。 推測で埋めない."""
    t = ("サンリオ シュガーバニーズ ふわふわ ぬいぐるみ ポーチ 全4種+ディスプレイ台紙セット"
         " ご当地本舗夢屋 ガチャポン ガチャガチャ コンプリート")
    assert extract_maker_text(t) == "ご当地本舗夢屋"   # スロットは取れている
    assert official_url(t) == ""                        # が URL は入れない


def test_no_slot_is_blank():
    """メーカー名が入らない店 (mirakikaku 等) は空欄."""
    t = "ゆらゆら おなまえ札めじるしチャーム2 全6種セット コンプ コンプリートセット"
    assert extract_maker_text(t) == ""
    assert official_url(t) == ""


def test_other_item_in_title_is_not_picked_up():
    """スロット外にメーカー名が出ても拾わない (店の「おすすめ商品」欄の誤検出対策)."""
    t = "キタンクラブ風 パロディ グッズ 全5種セット ご当地本舗夢屋 ガチャポン コンプリート"
    assert resolve_maker(t) == ""


def test_build_row_puts_official_url_in_col_i():
    row = build_row({
        "url": "https://item.rakuten.co.jp/auc-yuyou/g26074js01t/",
        "title": "虚無 KYOMU 全5種+ディスプレイ台紙セット エール ガチャポン ガチャガチャ コンプリート",
        "price_jpy": "2820",
    })
    assert row[COL_OFFICIAL_URL - 1] == "https://yell-world.jp/"


def test_build_row_leaves_col_i_blank_when_unknown():
    row = build_row({"url": "https://item.rakuten.co.jp/mirakikaku/c2511162/",
                     "title": "ゆらゆら おなまえ札めじるしチャーム2 全6種セット コンプ"})
    assert row[COL_OFFICIAL_URL - 1] == ""


def test_all_urls_are_https_or_http_and_unique():
    for name, url in MAKER_OFFICIAL.items():
        assert url.startswith(("http://", "https://")), name
    assert len(set(MAKER_OFFICIAL.values())) == len(MAKER_OFFICIAL)
