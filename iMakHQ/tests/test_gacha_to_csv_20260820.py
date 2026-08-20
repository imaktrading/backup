# -*- coding: utf-8 -*-
"""ガチャポン (楽天コンプ品) の出品CSV生成 (2026-08-20 新設).

中間スプシ93行を実測して分かったこと:
  - 40行が サンリオ (2026-06-29 に user が「今後扱わない」と決めた分)
  - 35行が ぬいぐるみ系。米国 CPSC では stuffed animals は **対象年齢の印字と
    無関係に** 児童製品確定なので、目視の年齢確認では逃げられない
  - 20組が「全N種セット」と「全N種+ディスプレイ台紙セット」の同じ商品
  - **全93行の1枚目が店のバナー画像**。1枚目は eBay のギャラリー画像になる
→ どれも黙って出すと事故になるので、生成側で落とす。
"""
from __future__ import annotations

import os
import sys

HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HQ, "tools"))

import gacha_to_csv as G                                        # noqa: E402


def _row(url="https://item.rakuten.co.jp/auc-yuyou/g1/", title="",
         pics="https://x/a.jpg", price="2820", cat="カプセルトイ", item_id=""):
    r = [""] * 18
    r[0], r[1], r[2], r[6], r[12], r[17] = url, item_id, title, pics, price, cat
    return r


TITLE = ("ちいさな アニマル スツール 2 全5種セット ディーアイエス "
         "ガチャポン ガチャガチャ コンプリート：遊you　楽天市場店")


class TestParsingTheJapaneseTitle:
    def test_shop_suffix_is_dropped(self):
        assert G.strip_shop_suffix(TITLE).endswith("コンプリート")

    def test_piece_count(self):
        assert G.piece_count(TITLE) == 5
        assert G.piece_count("全 10 種+ディスプレイ台紙セット") == 10
        assert G.piece_count("セット") is None

    def test_series_and_maker(self):
        assert G.series_jp(TITLE) == "ちいさな アニマル スツール 2"
        assert G.maker_jp(TITLE) == "ディーアイエス"

    def test_maker_is_not_guessed(self):
        """メーカー名が入らない店の行は空のまま (推測で埋めない)."""
        assert G.maker_jp("きどりっこ めじるしラバーチャーム 全5種セット コンプ") == ""

    def test_display_board_is_detected(self):
        assert G.has_display_board("全5種+ディスプレイ台紙セット") is True
        assert G.has_display_board("全5種セット") is False


class TestWhatMustNotBeListed:
    """CPSC。対象年齢の印字では逃げられない区分なので生成側で落とす."""

    def test_sanrio_is_blocked(self):
        assert "サンリオ" in G.blocked_reason("サンリオ ポムポムプリン 全4種セット")

    def test_plush_is_blocked_even_without_sanrio(self):
        for w in ("ぬいぐるみ", "マスコット", "フロッキー", "もこもこ"):
            assert G.blocked_reason(f"どうぶつ {w} 全5種セット") is not None

    def test_figures_are_fine(self):
        assert G.blocked_reason(TITLE) is None

    def test_blocked_rows_never_become_items(self):
        assert G.parse_row(_row(title="サンリオ クロミ 全4種セット")) is None


class TestRowsAreDroppedFailClosed:
    def test_missing_piece_count_is_dropped(self):
        assert G.parse_row(_row(title="なにか コンプリート")) is None

    def test_already_listed_row_is_dropped(self):
        assert G.parse_row(_row(title=TITLE, item_id="820022124251")) is None

    def test_other_category_is_dropped(self):
        assert G.parse_row(_row(title=TITLE, cat="TCG")) is None

    def test_no_price_is_dropped(self):
        assert G.parse_row(_row(title=TITLE, price="")) is None

    def test_a_good_row_parses(self):
        it = G.parse_row(_row(title=TITLE))
        assert it["pieces"] == 5 and it["cost_jpy"] == 2820
        assert it["maker_jp"] == "ディーアイエス"


class TestShopBannersAreNotProductPhotos:
    """バナー判定は残す (目視画面での並べ順やチェックの既定に使う)。

    ただし **行は落とさない** — G列は人が見て選ぶ (下の pass-through テスト)。
    """

    def test_known_banners_are_detected(self):
        assert G.is_banner("https://image.rakuten.co.jp/x/bn_math20130901tate.jpg")
        assert G.is_banner("https://image.rakuten.co.jp/mirakikaku/cabinet/rkanban.jpg")

    def test_product_photos_are_kept(self):
        assert not G.is_banner("https://image.rakuten.co.jp/x/cabinet/g260736s02t.jpg")

    def test_the_g_column_is_passed_through_untouched(self):
        """★2026-08-20 user 指示: G列は間引かず全部 目視画面に出す。

        744枚中667枚が店の部品だったが、機械には選り分けられない
        (`parts/header/menu0.jpg` のような物まで在る)。人が見て選ぶ。
        """
        it = G.parse_row(_row(title=TITLE,
                              pics="https://x/bn_math1.jpg|https://x/item1.jpg"))
        assert it["pics"] == ["https://x/bn_math1.jpg", "https://x/item1.jpg"]


class TestTitleAndDedup:
    # ★2026-08-20 にタイトルの形を入れ替えた (ユーザーが実際の出品を提示して確定)。
    #   旧: `<メーカー> <シリーズ> Full Set of N Gashapon NEW`
    #       → 先頭20字を検索されない語が占領し、題材が途中で切れていた
    #   新: `<題材(英語)> <形態> Complete Set N <メーカー> <カプセルの呼び方>`

    def test_題材が先頭_メーカーは後ろ(self):
        t = G.build_title("VIRUSWEETS Sweets Shop", 6, "Bandai", "Miniature Figure")
        assert t.startswith("VIRUSWEETS Sweets Shop")
        assert "Complete Set 6" in t and "Bandai Gashapon" in t

    def test_商標はメーカーで使い分ける(self):
        """`Gashapon` はバンダイの登録商標。他社商品に付けない."""
        assert "Gashapon" in G.build_title("X Figure", 5, "Bandai")
        t = G.build_title("X Figure", 5, "Takara Tomy A.R.T.S")
        assert "Gashapon" not in t and "Gacha" in t
        assert "Capsule Toy" in G.build_title("X Figure", 5, "Kitan Club")

    def test_title_stays_within_80(self):
        t = G.build_title("A" * 120, 5, "B" * 20)
        assert len(t) <= 80 and "Complete Set 5" in t

    def test_board_variants_collapse_to_one(self):
        """同じ商品の台紙あり/なしは1本に寄せる (同じ絵柄で2出品しない)."""
        a = {"series_jp": "アニマル スツール 2", "pieces": 5, "with_board": False}
        b = {"series_jp": "アニマル スツール 2", "pieces": 5, "with_board": True}
        got = G.dedup_board_variants([b, a])
        assert len(got) == 1 and got[0]["with_board"] is False

    def test_different_products_are_kept(self):
        a = {"series_jp": "X", "pieces": 5, "with_board": False}
        b = {"series_jp": "Y", "pieces": 5, "with_board": False}
        assert len(G.dedup_board_variants([a, b])) == 2


class TestSku:
    def test_rakuten_url(self):
        assert G.supply_sku("https://item.rakuten.co.jp/auc-yuyou/g260736s02t/") \
            == "g260736s02t"     # ★店名は入れない (2026-08-20 ユーザー確定)

    def test_mercari_url_keeps_the_existing_convention(self):
        assert G.supply_sku("https://jp.mercari.com/item/m86586660368") == "m86586660368"

    def test_unknown_url_gives_nothing(self):
        assert G.supply_sku("https://example.com/x") == ""
