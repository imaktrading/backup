"""tests/test_gacha_maker - ガチャのタイトルから メーカー公式URL を引く.

2026-08-20 新設 (user 依頼: I列に公式URL)。 実測で固定すること:
  - メーカー名は 「…セット <メーカー> ガチャポン…」 のスロットにしか無い
    (楽天の商品ページには メーカー欄が無い / 全文検索は同店の「おすすめ商品」を誤検出)
  - 表に無いメーカー・スロット無しは **空欄** (推測で URL を入れない)
"""
from __future__ import annotations

import pytest

from gacha_maker import MAKER_OFFICIAL, extract_maker_text, official_url, resolve_maker
from sheet_writer_rakuten import build_row

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


def test_maker_official_url_is_not_written_to_the_sheet():
    """★2026-08-21 変更: メーカーの **トップページ** はスプシに入れない (HQ 指摘)。

    I列は出品くんの英語タイトル列で、 トップページでは見比べにも画像取得にも使えない。
    スプシに入れるのは **公式の商品ページ** (V列) だけ。
    `gacha_maker.official_url` はメーカー判定の道具として残す。
    """
    row = build_row({"url": "https://item.rakuten.co.jp/auc-yuyou/g26074js01t/",
                     "title": "虚無 KYOMU 全5種セット エール ガチャポン コンプリート",
                     "price_jpy": "2820"})
    assert row[8] == ""


def test_all_urls_are_https_or_http_and_unique():
    for name, url in MAKER_OFFICIAL.items():
        assert url.startswith(("http://", "https://")), name
    assert len(set(MAKER_OFFICIAL.values())) == len(MAKER_OFFICIAL)


# --------------------------------------------------------------------------
# 収集対象メーカーの絞り込み (2026-08-20 user 確定)
# --------------------------------------------------------------------------
def test_allowed_makers_is_the_five_user_chose():
    from gacha_maker import ALLOWED_MAKERS
    assert ALLOWED_MAKERS == frozenset({
        "バンダイ", "タカラトミーアーツ", "クオリア", "キタンクラブ", "ブシロードクリエイティブ"})


@pytest.mark.parametrize("title,ok", [
    ("サンリオ ハローキティ 全4種+ディスプレイ台紙セット タカラトミーアーツ ガチャポン コンプリート", True),
    ("なにか 全5種セット キタンクラブ ガチャポン コンプリート", True),
    ("なにか 全5種セット ブシロード ガチャポン コンプリート", True),
    # 対象外メーカー
    ("サンリオ 全4種+ディスプレイ台紙セット ご当地本舗夢屋 ガチャポン コンプリート", False),
    ("なにか 全5種+ディスプレイ台紙セット トイズスピリッツ ガチャポン コンプリート", False),
    # メーカーが分からない物も採らない (fail-closed)
    ("ゆらゆら おなまえ札めじるしチャーム2 全6種セット コンプ", False),
])
def test_is_allowed(title, ok):
    from gacha_maker import is_allowed
    assert is_allowed(title) is ok


def test_is_allowed_uses_description_maker_field():
    from gacha_maker import is_allowed
    assert is_allowed("どうぶつの森 全8種セット", "メーカー：クオリア ラインナップ") is True
    assert is_allowed("どうぶつの森 全8種セット", "メーカー：日本オート玩具") is False
