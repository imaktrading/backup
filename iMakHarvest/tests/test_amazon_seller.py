"""amazon seller 判定 (= 直販 vs 第三者) のテスト.

2026-06-12: FBA 誤検出バグ (= 第三者販売 + Amazon 発送 を直販と誤判定) の回帰防止。
根本原因は body 全文 marker / 発送元(Ships from) marker での判定。
修正後は buybox merchantId="AN1VRQENFRJN5" を authoritative signal とする。
"""
from scrapers import amazon_item_detail as D
from scrapers import amazon_search_http as H


class _FakeEl:
    def __init__(self, text=""):
        self.text = text


class _FakeDriver:
    """_extract_seller 用の最小 selenium driver mock."""

    def __init__(self, page_source="", block_texts=None, seller_trigger=None,
                 buybox_rows=None):
        self.page_source = page_source
        self._block_texts = block_texts or []
        self._seller_trigger = seller_trigger
        self._buybox_rows = buybox_rows or []

    def find_elements(self, by, sel):
        if "tabular-buybox" in sel and "tabular-buybox-text" in sel:
            return [_FakeEl(t) for t in self._buybox_rows]
        # merchant/buybox block selectors
        return [_FakeEl(t) for t in self._block_texts]

    def find_element(self, by, sel):
        if sel == "#sellerProfileTriggerId":
            if self._seller_trigger is None:
                raise RuntimeError("no element")
            return _FakeEl(self._seller_trigger)
        raise RuntimeError("no element")


# --- HTTP detect_seller_amazon_jp ---

def test_http_detect_direct_by_merchant_id():
    html = '<div>...{"merchantId":"AN1VRQENFRJN5"}...</div>'
    assert H.detect_seller_amazon_jp(html) is True


def test_http_detect_non_direct_third_party_merchant_id():
    html = '<div>...{"merchantId":"A32HVTQLD51QUY"}...</div>'
    assert H.detect_seller_amazon_jp(html) is False


def test_http_detect_non_direct_amazon_us_merchant_id():
    # B000FPVUJA = Amazon US 並行輸入 (A1EJGP084HULR)
    html = '<div>...{"merchantId":"A1EJGP084HULR"}...</div>'
    assert H.detect_seller_amazon_jp(html) is False


# --- selenium _extract_seller ---

def test_selenium_direct_by_merchant_id():
    drv = _FakeDriver(page_source='..."merchantId":"AN1VRQENFRJN5"...')
    assert D._extract_seller(drv) == "Amazon.co.jp"


def test_selenium_fba_third_party_not_misclassified():
    """★ 回帰防止: 第三者販売 + Amazon 発送(FBA) を直販と誤検出しない."""
    drv = _FakeDriver(
        # 直販 merchantId は無い (= 第三者の merchantId のみ)
        page_source='..."merchantId":"A32HVTQLD51QUY"...',
        # buybox block: 販売元=第三者, 発送元=Amazon.co.jp (= FBA)
        block_texts=["販売元: 時計のセレクトショップ\n発送元: Amazon.co.jp"],
        seller_trigger="時計のセレクトショップ",
    )
    result = D._extract_seller(drv)
    assert result != "Amazon.co.jp"
    assert result == "時計のセレクトショップ"


def test_selenium_fba_third_party_blocks_ship_from_marker_only():
    """発送元 Amazon.co.jp だけが block にあっても直販と誤検出しない."""
    drv = _FakeDriver(
        page_source="<html>no direct merchant</html>",
        block_texts=["発送元 Amazon.co.jp"],  # Ships from のみ = FBA
        seller_trigger="並行輸入ショップ",
    )
    assert D._extract_seller(drv) == "並行輸入ショップ"


def test_selenium_direct_fallback_by_sale_marker():
    """merchantId 取れなくても block 内「販売: Amazon.co.jp」で直販 fallback."""
    drv = _FakeDriver(
        page_source="<html>no merchant id token</html>",
        block_texts=["販売: Amazon.co.jp\n発送元: Amazon.co.jp"],
    )
    assert D._extract_seller(drv) == "Amazon.co.jp"


def test_selenium_unknown_returns_empty():
    drv = _FakeDriver(page_source="<html></html>")
    assert D._extract_seller(drv) == ""
