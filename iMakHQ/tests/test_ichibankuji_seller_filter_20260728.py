"""一番くじのメルカリ セラーフィルタを PSA と同条件に統一 (2026-07-28 ユーザー指示).

一番くじは「新品 + 送料込み」だけで **セラー評価を見ていなかった**。
PSA 補URL は「送料込み + 個人セラーは評価件数≥100 (Shops は不問)」。
判定は mercari_psa_resource.candidate_passes_filter に一本化する (規約の二重実装を避ける)。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import ichibankuji_restock as I  # noqa: E402
import mercari_psa_resource as mp  # noqa: E402


class _Drv:
    """候補URLごとに固定の詳細 page_source を返すダミー。"""

    def __init__(self, pages):
        self.pages = pages
        self.page_source = ""

    def get(self, url):
        self.page_source = self.pages.get(url, "")


def _page(cond="新品、未使用", ship="送料込み", reviews=None):
    s = f"商品の状態 {cond} 配送料の負担 {ship}"
    if reviews is not None:
        s += f" {reviews}件のレビュー"
    return s


def _run(monkeypatch, cands, pages):
    monkeypatch.setattr(I.time, "sleep", lambda *_a: None)
    return I._filter_new_freeship(_Drv(pages), [dict(c) for c in cands])


def test_threshold_matches_psa_default():
    assert I.MIN_SELLER_REVIEWS == 100


def test_low_review_personal_seller_is_dropped(monkeypatch):
    url = "https://jp.mercari.com/item/m1"
    kept = _run(monkeypatch, [{"href": url, "price": 1000}], {url: _page(reviews=3)})
    assert kept == []


def test_high_review_personal_seller_is_kept(monkeypatch):
    url = "https://jp.mercari.com/item/m2"
    kept = _run(monkeypatch, [{"href": url, "price": 1000}], {url: _page(reviews=1282)})
    assert len(kept) == 1
    assert kept[0]["reviews"] == 1282


def test_shops_seller_is_kept_without_reviews(monkeypatch):
    """Shops(業者)は評価不問 — PSA と同じ扱い。"""
    url = "https://jp.mercari.com/shops/product/ABC"
    kept = _run(monkeypatch, [{"href": url, "price": 1000}], {url: _page()})
    assert len(kept) == 1


def test_missing_reviews_on_personal_is_failclosed(monkeypatch):
    """評価件数が取れない個人出品は落とす (fail-closed)。"""
    url = "https://jp.mercari.com/item/m3"
    kept = _run(monkeypatch, [{"href": url, "price": 1000}], {url: _page(reviews=None)})
    assert kept == []


def test_used_condition_still_dropped(monkeypatch):
    """状態フィルタ(新品のみ)は従来どおり維持。評価が高くても中古は落とす。"""
    url = "https://jp.mercari.com/item/m4"
    kept = _run(monkeypatch, [{"href": url, "price": 1000}],
                {url: _page(cond="やや傷や汚れあり", reviews=999)})
    assert kept == []


def test_cash_on_delivery_still_dropped(monkeypatch):
    url = "https://jp.mercari.com/item/m5"
    kept = _run(monkeypatch, [{"href": url, "price": 1000}],
                {url: _page(ship="着払い", reviews=999)})
    assert kept == []


def test_uses_psa_decision_function():
    """判定の本体は PSA 側の純関数であること (両者がズレない保証)。"""
    assert mp.candidate_passes_filter("新品、未使用", "送料込み", 3, False, min_reviews=100) is False
    assert mp.candidate_passes_filter("新品、未使用", "送料込み", 3, True, min_reviews=100) is True
