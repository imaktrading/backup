"""Chrome 版のメルカリ判定は要素だけで決める — 2026-10-04 ADV 依頼 (ユーザー GO).

旧版は Shops の本文に「在庫切れ」「売り切れ」があれば売切にしていた。商品説明にその言葉を
書くお店 (カードショップ ドンドン 等) を誤って売切にし、9月に4件が売切⇔在庫ありを往復した。
"""
import types

import scrapers.mercari_scraper as m


class FakeDriver:
    def __init__(self, testids=(), body="", btn_class="", btn_disabled=None):
        self.testids = set(testids)
        self.body = body
        self.btn = types.SimpleNamespace(
            get_attribute=lambda k: {"class": btn_class, "disabled": btn_disabled}.get(k),
            text="購入手続きへ")

    def get(self, url):
        pass

    def find_elements(self, by, sel):
        hits = []
        for part in sel.split(","):
            part = part.strip()
            tid = part.split('"')[1] if '"' in part else ""
            if tid in self.testids:
                hits.append(self.btn)
        return hits

    def find_element(self, by, sel):
        if sel == "body":
            return types.SimpleNamespace(text=self.body)
        hits = self.find_elements(by, sel)
        if not hits:
            from selenium.common.exceptions import NoSuchElementException
            raise NoSuchElementException(sel)
        return hits[0]


SHOPS = "https://jp.mercari.com/shops/product/2JUr6k9sRTwJ3Pji2DtVKW"


def _fast(monkeypatch):
    monkeypatch.setattr(m, "SELENIUM_WAIT_SEC", 0.3)
    monkeypatch.setattr(m, "SELENIUM_POLL_INTERVAL", 0.01)
    monkeypatch.setattr(m, "_save_failure_snapshot", lambda *a, **k: None)


def test_shops_description_soldout_words_do_not_make_sold(monkeypatch):
    _fast(monkeypatch)
    d = FakeDriver(testids={"product-detail-container", "variant-purchase-button"},
                   body="在庫残り1点\n購入手続きへ\n…在庫切れとなる場合がございます。万が一売り切れの場合には…")
    r = m._detect_via_selenium(d, SHOPS, True)
    assert r["in_stock"] is True


def test_shops_description_words_without_button_is_unreadable_not_sold(monkeypatch):
    # 購入ボタンが描画される前 (= 説明文だけ見えている) は売切にせず判定不能
    _fast(monkeypatch)
    d = FakeDriver(testids={"product-detail-container"}, body="在庫切れとなる場合がございます。売り切れ")
    assert m._detect_via_selenium(d, SHOPS, True) is None


def test_shops_out_of_stock_element_is_sold(monkeypatch):
    _fast(monkeypatch)
    d = FakeDriver(testids={"product-detail-container", "out-of-stock", "disabled-purchase-button"},
                   body="売り切れ\n購入手続きへ")
    assert m._detect_via_selenium(d, SHOPS, True)["in_stock"] is False


def test_shops_disabled_button_class_is_sold(monkeypatch):
    _fast(monkeypatch)
    d = FakeDriver(testids={"product-detail-container", "variant-purchase-button"}, btn_class="x disabled__y")
    assert m._detect_via_selenium(d, SHOPS, True)["in_stock"] is False


def test_deleted_page_without_product_frame(monkeypatch):
    _fast(monkeypatch)
    d = FakeDriver(testids=set(), body="ページが見つかりませんでした\nお探しのページは…削除された可能性があります。")
    assert m._detect_via_selenium(d, SHOPS, True)["status"] == "DELETED"


def test_deletion_words_inside_product_page_are_ignored(monkeypatch):
    _fast(monkeypatch)
    d = FakeDriver(testids={"product-detail-container"}, body="この商品は削除されました と説明文に書いてある")
    assert m._detect_via_selenium(d, SHOPS, True) is None


def test_error_page_is_unreadable_not_deleted(monkeypatch):
    _fast(monkeypatch)
    d = FakeDriver(testids=set(), body="エラーが発生しました")
    assert m._detect_via_selenium(d, "https://jp.mercari.com/item/m1", False) is None


def test_item_deleted_page(monkeypatch):
    _fast(monkeypatch)
    d = FakeDriver(testids=set(), body="該当する商品は削除されています。")
    assert m._detect_via_selenium(d, "https://jp.mercari.com/item/m70161110227", False)["status"] == "DELETED"
