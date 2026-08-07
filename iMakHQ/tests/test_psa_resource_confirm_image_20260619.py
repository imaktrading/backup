# -*- coding: utf-8 -*-
"""RESTOCK確証の画像解決 回帰テスト (2026-06-19)。

真因: _resolve_image_url(mercari出品ページ→CDN直画像 / snkrdunk→og:image)が
定義only・/img プロキシに未配線だった。candidate の出品ページURLをそのまま画像として
掴み、全候補が「画像なし」になっていた。修正: do_GET の /img で _fetch_image 前に
_resolve_image_url をかます。ここでは解決関数のルーティングを固定する。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

import psa_resource_confirm as prc


def test_mercari_item_resolves_to_static_cdn():
    """mercari item (m<id>) ページURL → 静的CDN直画像(ページ取得不要)。"""
    u = "https://jp.mercari.com/item/m12345678901"
    got = prc._resolve_image_url(u)
    assert got == "https://static.mercdn.net/item/detail/orig/photos/m12345678901_1.jpg"


def test_direct_mercdn_image_passthrough():
    """既に mercdn の直画像URLはそのまま(二重解決しない)。"""
    u = "https://static.mercdn.net/item/detail/orig/photos/m12345678901_1.jpg"
    assert prc._resolve_image_url(u) == u


def test_catalog_or_ebay_image_passthrough():
    """catalog/eBay の直画像URLはそのまま。"""
    u = "https://i.ebayimg.com/00/s/abc/z/xyz/$_57.JPG"
    assert prc._resolve_image_url(u) == u


def test_snkrdunk_page_uses_og_image(monkeypatch):
    """snkrdunk 商品ページ → og:image 解決(ネットワークは monkeypatch)。"""
    monkeypatch.setattr(prc, "_fetch_og_image", lambda url: "https://cdn.snkrdunk.com/og/abc.jpg")
    u = "https://snkrdunk.com/trading-cards/12345"
    assert prc._resolve_image_url(u) == "https://cdn.snkrdunk.com/og/abc.jpg"


def test_mercari_shops_no_itemid_uses_og(monkeypatch):
    """mercari shops 等 m<id> が無いページ → og:image。"""
    monkeypatch.setattr(prc, "_fetch_og_image", lambda url: "https://cdn.mercari/og.jpg")
    u = "https://jp.mercari.com/shops/product/abcXYZ"
    assert prc._resolve_image_url(u) == "https://cdn.mercari/og.jpg"


def test_snkrdunk_cdn_thumbnail_passthrough():
    """SNKRDUNK 実カード画像(cdn.snkrdunk.com の thumbnailUrl)は og:image 解決せずそのまま。

    回帰: listing ページの og:image はサイト既定ロゴで全候補同一になる → thumbnailUrl を直使い。
    cdn URL を再度 og 解決すると壊れるため passthrough を固定。
    """
    u = "https://cdn.snkrdunk.com/upload_bg_removed/20260130065226-0.webp?size=m"
    assert prc._resolve_image_url(u) == u


def test_image_extension_passthrough_no_og(monkeypatch):
    """画像拡張子で終わる URL は og:image 解決を呼ばずそのまま(誤って og を引かない)。"""
    monkeypatch.setattr(prc, "_fetch_og_image", lambda url: "SHOULD_NOT_BE_CALLED")
    assert prc._resolve_image_url("https://x.test/a/b.webp?size=m") == "https://x.test/a/b.webp?size=m"
    assert prc._resolve_image_url("https://x.test/a/b.PNG") == "https://x.test/a/b.PNG"


def test_snkrdunk_product_page_still_uses_og(monkeypatch):
    """SNKRDUNK の商品ページURL(画像でない)は従来どおり og:image 解決(後方互換)。"""
    monkeypatch.setattr(prc, "_fetch_og_image", lambda url: "https://cdn.snkrdunk.com/og/x.jpg")
    assert prc._resolve_image_url("https://snkrdunk.com/trading-cards/12345") == \
        "https://cdn.snkrdunk.com/og/x.jpg"


def test_parse_restock_result_confirmed_and_diffs():
    """RESTOCK確証 POST → 買う候補(urls) + 違う個別(diffs=どの候補が別カードか) + 見送り件数。"""
    data = {
        "confirmed": [{"idx": 0, "urls": ["u1", "", "u2"]}, {"idx": 1, "urls": []}],
        "diffs": [{"idx": 2, "url": "wrong1"}, {"idx": 5, "url": "wrong2"}],
        "skip": 5,
    }
    r = prc.parse_restock_result(data)
    assert r["confirmed"] == [{"idx": 0, "urls": ["u1", "u2"]}]   # 空url除去 / urls空のcardは落ちる
    assert r["diffs"] == [{"idx": 2, "url": "wrong1"}, {"idx": 5, "url": "wrong2"}]  # 個別=即対応用
    assert r["skip"] == 5


def test_parse_restock_result_missing_fields():
    """diffs/skip 欠落でも安全(後方互換)。"""
    r = prc.parse_restock_result({"confirmed": [{"idx": 3, "urls": ["x"]}]})
    assert r["confirmed"] == [{"idx": 3, "urls": ["x"]}]
    assert r["diffs"] == []
    assert r["skip"] == 0


def test_parse_restock_result_empty():
    r = prc.parse_restock_result({})
    assert r["confirmed"] == []
    assert r["diffs"] == []
    assert r["skip"] == 0


def test_empty_url():
    assert prc._resolve_image_url("") == ""
    assert prc._resolve_image_url(None) == ""


# ============================================================================
# ラベル書式ゆれ対策 (2026-08-02)
# PSA は同じカードに複数の印字書式を使う。実例(どちらも OP09-050 ナミ ALTERNATE ART・柄も同一):
#   cert 97317368  "2024 ONE PIECE JPN."    / "OP09-ALTERNATE ART"
#   cert 165347848 "2024 ONE PIECE OP09 JP" / "ALTERNATE ART"
# ユーザー報告: 「画像は酷似していてラベルが違えば、違うカードと目視で判別してしまう」
# = 同一カードを「違う」と押して使える仕入元を捨てる。UI に判定材料と注意書きを出して防ぐ。
# ============================================================================


def test_variety_is_split_from_subject():
    assert prc.split_subject_variety("NAMI ALTERNATE ART") == ("NAMI", "ALTERNATE ART")
    assert prc.split_subject_variety("GLACEON VSTAR SPECIAL CARD SET") == (
        "GLACEON VSTAR", "SPECIAL CARD SET")


def test_unknown_variety_is_left_blank_not_guessed():
    # 既知の変種語が無ければ空欄。推測して埋めると誤った根拠を人に見せることになる。
    assert prc.split_subject_variety("NAMI") == ("NAMI", "")
    assert prc.split_subject_variety("") == ("", "")


def test_label_facts_fall_back_to_card_no_when_cert_unknown():
    f = prc.psa_label_facts("0000000000", "OP09-050")
    assert f["number"] == "OP09-050" and f["variety"] == "" and f["brand"] == ""


def _html_one(**over):
    it = {"idx": 0, "title": "Nami R-P [OP09-050]", "card_no": "OP09-050",
          "ebay_url": "https://x", "ref_image": "https://img/a.jpg",
          "candidates": [{"channel": "mercari", "url": "https://jp.mercari.com/item/m1",
                          "price": 16800, "name": "ナミ OP09-050"}]}
    it.update(over)
    return prc.build_restock_html([it])


def test_label_notice_is_always_shown():
    h = _html_one()
    assert "ラベルの書き方が違っても" in h
    assert "番号" in h and "変種名" in h and "絵柄" in h
    assert "根拠になりません" in h


def test_identity_chips_show_number_and_variety():
    h = _html_one(psa_label={"number": "OP09-050", "variety": "ALTERNATE ART",
                             "brand": "ONE PIECE JAPANESE OP09-EMPERORS IN THE NEW WORLD"})
    assert "class='idf'" in h
    assert "ALTERNATE ART" in h and "OP09-050" in h


def test_identity_chips_absent_when_no_label_facts():
    # psa_label を渡さない呼出(RESTOCKゲート等)は非表示 = 後方互換
    assert "class='idf'" not in _html_one()


def test_action_bar_precedes_heading_so_buttons_stay_visible():
    """全部ON/OFF が h1 の下に潜って押せなくなる回帰を防ぐ。

    h1 は文言が長く2〜3行に折り返すため実高さが変わる。旧CSSは .bar を top:46px 固定で
    敷いていたので、折り返すと bar が h1 の裏に隠れた(ユーザー報告 2026-08-02)。
    """
    for h in (_html_one(), prc.build_confirm_html([{"idx": 0, "title": "t", "card_no": "OP09-050",
                                                    "candidates": [], "ebay_url": "https://x"}])):
        assert h.index("class='bar'") < h.index("<h1>"), "bar が h1 より後ろ = 隠れる配置"
    assert ".bar{position:sticky;top:0" in prc._CSS
    assert "position:sticky" not in prc._CSS.split("\n")[1]   # h1 行に sticky を残さない
