"""_process_one の detail_fn (API版詳細取得) 配線テスト (2026-10-02 段階②).

detail_fn が全件成功すれば Chrome driver を1本も起動しない (lazy) ことと、
detail_fn が None を返した時に Chrome へフォールバックすることを検証する。
"""
from __future__ import annotations

import types

import pytest

import run_harvest_mercari_psa10 as R

pytestmark = pytest.mark.offline


def _args(**over):
    base = dict(price_min=3000, price_max=100000, min_rating=100, no_identity=False,
               strict_gates=False, cost_cfg={"max_jpy": 1_000_000}, card_limits={})
    base.update(over)
    return types.SimpleNamespace(**base)


def _valid_detail(url, seller_quality=None):
    return {
        "title": "PSA10 ピカチュウ", "price_jpy": 5000, "condition": "",
        "description": "", "image_urls": ["https://x/1.jpg"], "in_stock": True,
        "status": "ON_SALE",
        "seller_quality": seller_quality or {
            "rating_count": 200, "star": 5.0, "identity_verified": True,
        },
    }


@pytest.fixture(autouse=True)
def _stub_vision_and_gates(monkeypatch):
    monkeypatch.setattr(R.psa_slab_vision, "read_slab",
                        lambda images: {"cert": "153420191", "grade": "GEM MT 10",
                                       "label": "L", "card_number": "1", "year": "2024",
                                       "error": ""})
    monkeypatch.setattr(R.psa_cert, "local_gate",
                        lambda vision, title: {"ok": True})
    monkeypatch.setattr(R.psa_grade_gate, "looks_like_psa10",
                        lambda **k: True)
    monkeypatch.setattr(R.psa_grade_gate, "is_bundle", lambda title: False)


def test_detail_fn_success_never_touches_chrome(monkeypatch):
    def boom_driver_getter():
        raise AssertionError("detail_fn が成功しているのに Chrome driver を起動した")

    def detail_fn(url):
        return _valid_detail(url)

    kept = R._process_one(
        "https://jp.mercari.com/item/m1", boom_driver_getter, _args(), {"urls": set(), "certs": set()},
        {"sold": 0, "seller_rating": 0, "no_identity": 0, "fetch_fail": 0, "no_image": 0,
         "cert_unreadable": 0, "vision_error": 0, "already_claimed_url": 0,
         "already_claimed_cert": 0, "item_error": 0},
        [], detail_fn=detail_fn,
    )
    assert kept is not None
    assert kept["url"] == "https://jp.mercari.com/item/m1"


def test_detail_fn_none_falls_back_to_chrome(monkeypatch):
    calls = {"driver": 0}

    def driver_getter():
        calls["driver"] += 1
        return types.SimpleNamespace()

    monkeypatch.setattr(R.mercari_item_detail, "fetch_detail",
                        lambda driver, url: _valid_detail(url))
    monkeypatch.setattr(R.MSch, "extract_seller_quality",
                        lambda driver: {"rating_count": 200, "star": 5.0, "identity_verified": True})
    monkeypatch.setattr(R.MSch, "passes_seller_filter", lambda q, **k: True)

    kept = R._process_one(
        "https://jp.mercari.com/item/m1", driver_getter, _args(), {"urls": set(), "certs": set()},
        {"sold": 0, "seller_rating": 0, "no_identity": 0, "fetch_fail": 0, "no_image": 0,
         "cert_unreadable": 0, "vision_error": 0, "already_claimed_url": 0,
         "already_claimed_cert": 0, "item_error": 0},
        [], detail_fn=lambda url: None,
    )
    assert kept is not None
    assert calls["driver"] >= 1  # フォールバックしたので Chrome driver に触った


def test_collect_with_detail_fn_only_never_creates_driver(monkeypatch, tmp_path):
    """collect() レベルでも、urls_overrideありdetail_fn全件成功なら Chrome を起動しない。"""
    def boom_create(headless=False):
        raise AssertionError("detail_fnが全件成功しているのにChromeを起動した")

    monkeypatch.setattr(R.MS, "create_anonymous_driver", boom_create)

    def detail_fn(url):
        return _valid_detail(url)

    got = R.collect(
        _args(keywords=["x"], games=None, max_details=0, manual=False, headless=True,
              no_dedupe=True, save_every=10, sheet_every=100, max_consecutive_errors=3),
        dump_path=tmp_path / "d.json",
        urls_override=["https://jp.mercari.com/item/m1", "https://jp.mercari.com/item/m2"],
        detail_fn=detail_fn,
    )
    assert len(got["candidates"]) == 2
