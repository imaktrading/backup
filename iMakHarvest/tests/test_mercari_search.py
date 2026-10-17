"""mercari_search の純関数テスト (URL builder / seller品質 parse / filter)."""
import types

import pytest

from scrapers.mercari_search import (
    build_search_url,
    collect_multi_keyword_urls,
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


@pytest.mark.parametrize("title,expected", [
    ("PORTER タンカー ショルダーバッグ 黒", True),
    ("ポーター TANKER ボディバッグ", True),
    ("PORTER ボストンバッグ ブラック", False),          # 非タンカー
    ("PORTER フレーム ヘルメットバッグ", False),         # 別シリーズ
    ("", False),
])
def test_is_tanker(title, expected):
    from scrapers.mercari_search import is_tanker
    assert is_tanker(title) is expected


@pytest.mark.parametrize("title", [
    "FADEN 2WAY ショルダーバッグ 検ポーター",      # 別ブランド
    "《THE NORTH FACE》ヘルメットバッグ 検ポーター",  # 別ブランド
])
def test_other_brand_excluded(title):
    from scrapers.mercari_search import is_target_bag
    assert is_target_bag(title) is False


# --------------------------------------------------------------------------
# collect_multi_keyword_urls: 検索中の1語クラッシュで全体を殺さない (2026-10-16 HQ依頼)
# --------------------------------------------------------------------------

def test_search_crash_skips_keyword_and_rebuilds_driver(monkeypatch):
    """1語で例外→その語だけ crashed_keywords へ、 driver_factory で作り直して次の語へ進む."""
    import scrapers.mercari_search as MSch

    def _fake_collect(keyword, driver, **kw):
        if keyword == "落ちる語":
            raise RuntimeError("chrome not reachable")
        return {"keyword": keyword, "url": "u", "urls": [f"https://x/{keyword}"],
                "cap_hit": False, "total_seen": 1}

    monkeypatch.setattr(MSch, "collect_search_listing_urls", _fake_collect)

    old_driver = types.SimpleNamespace(quit=lambda: None, tag="old")
    rebuilds = []

    def _factory():
        rebuilds.append(1)
        return types.SimpleNamespace(quit=lambda: None, tag="new")

    got = collect_multi_keyword_urls(
        ["語1", "落ちる語", "語2"], old_driver, driver_factory=_factory)

    assert got["crashed_keywords"] == ["落ちる語"]
    assert "落ちる語" not in got["by_keyword"]      # 次回また検索対象になる
    assert got["by_keyword"] == {"語1": 1, "語2": 1}
    assert len(rebuilds) == 1                        # 作り直しは1回


def test_on_new_urls_called_per_keyword_and_can_stop_search(monkeypatch):
    """🥕2026-10-17 HQ依頼 №610: 打ち切ったら残りの語は検索しない (検索と detail を交互に)."""
    import scrapers.mercari_search as MSch

    def _fake_collect(keyword, driver, **kw):
        return {"keyword": keyword, "url": "u", "urls": [f"https://x/{keyword}/a", f"https://x/{keyword}/b"],
                "cap_hit": False, "total_seen": 2}

    monkeypatch.setattr(MSch, "collect_search_listing_urls", _fake_collect)

    seen_batches = []

    def _on_new_urls(new_urls, kw):
        seen_batches.append((kw, list(new_urls)))
        return kw == "語2"  # 語2の処理後に打ち切る

    got = collect_multi_keyword_urls(
        ["語1", "語2", "語3"], types.SimpleNamespace(quit=lambda: None),
        on_new_urls=_on_new_urls)

    assert [kw for kw, _ in seen_batches] == ["語1", "語2"]   # 語3は検索していない
    assert got["stopped_early"] is True
    assert "語3" not in got["by_keyword"]                     # 次回また検索対象


def test_should_pause_stops_before_next_keyword_search(monkeypatch):
    """should_pause が真なら、 次の語の検索自体を始めない."""
    import scrapers.mercari_search as MSch

    calls = []

    def _fake_collect(keyword, driver, **kw):
        calls.append(keyword)
        return {"keyword": keyword, "url": "u", "urls": [f"https://x/{keyword}"],
                "cap_hit": False, "total_seen": 1}

    monkeypatch.setattr(MSch, "collect_search_listing_urls", _fake_collect)

    got = collect_multi_keyword_urls(
        ["語1", "語2", "語3"], types.SimpleNamespace(quit=lambda: None),
        should_pause=lambda: len(calls) >= 1)

    assert calls == ["語1"]              # 語2・語3は検索していない
    assert got["stopped_early"] is True


def test_search_crash_without_factory_still_raises(monkeypatch):
    """driver_factory を渡さなければ従来どおり例外を伝える (後方互換)."""
    import scrapers.mercari_search as MSch

    def _boom(keyword, driver, **kw):
        raise RuntimeError("chrome not reachable")

    monkeypatch.setattr(MSch, "collect_search_listing_urls", _boom)
    with pytest.raises(RuntimeError):
        collect_multi_keyword_urls(["語1"], types.SimpleNamespace(quit=lambda: None))
