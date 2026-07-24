"""メルカリ補URL候補フィルタ(送料込み + 個人セラー評価件数≥N)の純関数テスト (2026-07-25)。

ユーザー要望: 補URL候補は「送料込み(着払い除外) + 個人セラーは評価**件数**≥100(星でなく件数)、
Shopsは評価不問」。パターンは実レンダHTMLで検証済(_parse_cond_ship='送料込み' / '1282件のレビュー')。
純関数のみ (network非依存)。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from mercari_psa_resource import (
    _is_shops_url,
    _parse_cond_ship,
    _parse_seller_reviews,
    candidate_passes_filter,
)

# 実レンダHTMLの seller aria-label 実物(件数=1282 / 星=4.5)。件数を使い星は使わない。
_SELLER = '<div class="..._info" aria-label="mami, 1282件のレビュー, 5段階評価中4.5, 本人確認済">'
_DETAIL_SnkFree = "商品の状態</span><span>新品、未使用</span> 配送料の負担</span><span>送料込み</span>" + _SELLER
_DETAIL_Chakubarai = "配送料の負担</span><span>着払い</span>" + _SELLER


def test_parse_ship_label_adjacent_not_fullpage():
    # ページに着払い語が別所にあっても、ラベル直後の値を取る
    s = "関連: 着払い の商品 … 配送料の負担</span><span>送料込み</span>"
    assert _parse_cond_ship(s)[1] == "送料込み"
    assert _parse_cond_ship(_DETAIL_Chakubarai)[1] == "着払い"


def test_parse_seller_reviews_uses_count_not_star():
    assert _parse_seller_reviews(_SELLER) == 1282           # 件数(星4.5は無視)
    assert _parse_seller_reviews("5段階評価中4.5") is None   # 星だけ=件数なし
    assert _parse_seller_reviews("1,024件のレビュー") == 1024  # カンマ区切り
    assert _parse_seller_reviews("") is None


def test_is_shops_url():
    assert _is_shops_url("https://jp.mercari.com/shops/product/abc")
    assert not _is_shops_url("https://jp.mercari.com/item/m123")


def test_individual_needs_freeship_and_reviews():
    # 個人: 送料込み + 評価件数≥100
    assert candidate_passes_filter("新品、未使用", "送料込み", 1282, is_shops=False, min_reviews=100)
    assert not candidate_passes_filter("新品、未使用", "着払い", 1282, is_shops=False)   # 着払い→除外
    assert not candidate_passes_filter("新品、未使用", "送料込み", 40, is_shops=False, min_reviews=100)  # 評価不足
    assert not candidate_passes_filter("新品、未使用", "送料込み", None, is_shops=False)  # 評価取れず=除外(fail-closed)


def test_shops_exempt_from_reviews_but_needs_freeship():
    # Shops(業者): 評価不問だが送料込みは必要
    assert candidate_passes_filter("新品、未使用", "送料込み", None, is_shops=True, min_reviews=100)
    assert not candidate_passes_filter("新品、未使用", "着払い", None, is_shops=True)


def test_require_freeship_can_be_disabled():
    assert candidate_passes_filter("", "着払い", 1282, is_shops=False, min_reviews=100, require_freeship=False)
