"""mercari_search の純関数テスト (URL builder / seller品質 parse / filter)."""
import pytest

from scrapers.mercari_search import (
    build_search_url,
    parse_seller_quality,
    passes_seller_filter,
)

pytestmark = pytest.mark.offline


def test_build_search_url_full():
    u = build_search_url("PORTER ショルダーバッグ", 10000, 30000)
    assert u.startswith("https://jp.mercari.com/search?")
    assert "keyword=PORTER%20" in u
    assert "status=on_sale" in u
    assert "shipping_payer_id=2" in u
    assert "price_min=10000" in u
    assert "price_max=30000" in u


def test_build_search_url_no_price():
    u = build_search_url("PORTER")
    assert "price_min" not in u and "price_max" not in u
    assert "shipping_payer_id=2" in u and "status=on_sale" in u


@pytest.mark.parametrize("label,cnt,star,ident", [
    ("ぼー, 323件のレビュー, 5段階評価中5, 本人確認済", 323, 5.0, True),
    ("たろう, 1,024件のレビュー, 5段階評価中4.8", 1024, 4.8, False),  # 本人確認なし
    ("新規, 0件のレビュー", 0, None, False),
    ("名前だけ", None, None, False),
    ("", None, None, False),
])
def test_parse_seller_quality(label, cnt, star, ident):
    q = parse_seller_quality(label)
    assert q["rating_count"] == cnt
    assert q["star"] == star
    assert q["identity_verified"] is ident


def test_passes_seller_filter_threshold():
    # 評価100+ かつ 本人確認済 → 通す
    assert passes_seller_filter({"rating_count": 323, "identity_verified": True}) is True
    # 評価不足 → 弾く
    assert passes_seller_filter({"rating_count": 99, "identity_verified": True}) is False
    # 本人確認なし → 弾く
    assert passes_seller_filter({"rating_count": 500, "identity_verified": False}) is False
    # 評価数不明 → fail-closed で弾く
    assert passes_seller_filter({"rating_count": None, "identity_verified": True}) is False


def test_passes_seller_filter_identity_optional():
    # require_identity=False なら本人確認なしでも評価数だけで通す
    assert passes_seller_filter(
        {"rating_count": 150, "identity_verified": False},
        require_identity=False) is True


@pytest.mark.parametrize("title,expected", [
    # 本命バッグ → keep
    ("PORTER ポーター ショルダーバッグ 黒", True),
    ("PORTER タンカー ボディバック 斜め掛け", True),      # バック表記ゆれ
    ("PORTER / HEAT WAIST BAG BLACK", True),               # 英語BAG
    ("希少 PORTER タンカー 3WAY セージグリーン", True),   # 3WAY
    ("PORTER ボストンバッグ ブラック", True),
    ("PORTER ボディバッグ ウエストポーチ オリーブ", True),
    # off-target → reject
    ("新品 PORTER カレント ラウンドファスナー ブラック", False),  # 財布
    ("PORTER タンカー リュック 黒", False),                        # リュック
    ("[極美品] PORTER タンカー バックパック", False),              # バックパック
    ("レア TENDERLOIN PORTER バックパック リュック", False),       # コラボ
    ("PORTER digawel 別注 ナップサック", False),                    # 別注/ナップサック
    ("PORTER タンカー マルチポーチ ブラック", False),              # 小物ポーチ(バッグ語なし)
    ("PORTER 財布 二つ折り", False),
    ("", False),
])
def test_is_target_bag(title, expected):
    from scrapers.mercari_search import is_target_bag
    assert is_target_bag(title) is expected
