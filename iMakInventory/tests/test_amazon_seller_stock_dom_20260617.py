"""amazon scraper の新 DOM (2026-06-17) seller/stock 判定 regression.

Amazon が buy-box を JS prose 化し、 旧ラベル「販売元 Amazon.co.jp」「id=outOfStock」
「add-to-cart-button」が DOM から消滅 → _detect_seller 全件 unknown → 全件 fail-closed (None)
→ LOW amazon 15-19件 持続エラー (= 在庫切れ/3rd 検知不能 = 潜在 fail-OPEN)。

新 prose マーカー (実検体5件 row506/535=直販, row115/118/524=3rd の rendered DOM で確認):
- 第三者: "この商品は、出品者によって配送されます"
- Amazon直販: "Amazon.co.jp が発送"
- 在庫: #availability div の "在庫あり"/"残りN点"/"通常X日以内に発送"

boilerplate 罠 (素朴な部分一致だと誤判定する):
- "Amazon.co.jp が販売している商品と同様に" = FBA 説明文 (= その商品の販売元ではない)
- 出品者 description の "在庫切れの心配もありません" = 宣伝文 (= 在庫状態ではない)
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scrapers.amazon_scraper import _detect_seller, _detect_stock  # noqa: E402


def _avail(text):
    return f'<div id="availability" class="a-section"><span class="a-color-success">{text}</span></div>'


# --- _detect_seller ---

def test_seller_amazon_direct_prose():
    assert _detect_seller('... Amazon.co.jp が発送 ...')[0] == 'amazon'


def test_seller_third_party_prose():
    assert _detect_seller('... この商品は、出品者によって配送されます。 ...')[0] == 'third_party'


def test_seller_boilerplate_not_mistaken_for_amazon():
    """FBA 説明 boilerplate "Amazon.co.jp が販売している商品と同様に" を直販と誤判定しない。
    出品者配送マーカーがあれば third_party が優先される。"""
    html = ('フルフィルメント by Amazon の商品は、Amazon.co.jp が販売している商品と同様に'
            '国内配送料無料... この商品は、出品者によって配送されます。')
    assert _detect_seller(html)[0] == 'third_party'


def test_seller_unknown_when_no_marker():
    assert _detect_seller('<div>price only, no seller marker</div>')[0] == 'unknown'


# --- _detect_stock (seller gate 統合) ---

def test_stock_amazon_direct_zaiko_ari():
    html = _avail('在庫あり。') + 'Amazon.co.jp が発送'
    verdict, _ = _detect_stock(html)
    assert verdict is True


def test_stock_amazon_direct_nokori_n_ten():
    """新 DOM: #availability "残りN点" + Amazon発送 → in_stock=True。"""
    html = _avail('残り1点 ご注文はお早めに') + 'Amazon.co.jp が発送'
    verdict, _ = _detect_stock(html)
    assert verdict is True


def test_stock_amazon_direct_tsujo_hassou():
    html = _avail('通常2～3日以内に発送します。') + 'Amazon.co.jp が発送'
    assert _detect_stock(html)[0] is True


def test_stock_third_party_is_false_takedown():
    """出品者配送 = 第三者 → 在庫あり表示でも取下げ対象 (Rule 0)。"""
    html = _avail('在庫あり。') + 'この商品は、出品者によって配送されます。'
    assert _detect_stock(html)[0] is False


def test_stock_soldout_in_availability():
    html = _avail('現在在庫切れです。') + 'Amazon.co.jp が発送'
    assert _detect_stock(html)[0] is False


def test_stock_boilerplate_soldout_phrase_ignored():
    """出品者 description の "在庫切れの心配もありません" は #availability 外なので無視され、
    #availability の在庫あり + Amazon発送 で True (= boilerplate 誤検出しない)。"""
    html = (_avail('残り3点') + 'Amazon.co.jp が発送'
            + '<div id="productDescription">Amazon専売品なので在庫切れの心配もありません</div>')
    assert _detect_stock(html)[0] is True


def test_stock_unknown_seller_failclosed():
    """seller 不明 + 在庫あり → fail-closed (None)。 誤って True にしない (Rule 0 厳格)。"""
    html = _avail('残り3点')  # seller マーカーなし
    verdict, reason = _detect_stock(html)
    assert verdict is None
