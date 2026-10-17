"""tests/test_credit_exhaustion - 残高切れでその場で止める (2026-10-18 HQ依頼 B-20261018-001).

事故: 10/17 22:18 にAnthropicの残高切れが起きた後も、1件ずつ「不鮮明」扱いで流して
7時間半・1,955件分 空回りした。残高切れ・請求系の障害は検出した瞬間に走行全体を
止め、残りの語の検索もしない。
"""
from __future__ import annotations

import types

import pytest

import run_harvest_mercari_psa10 as R

pytestmark = pytest.mark.offline


def _args(**over):
    base = dict(
        price_min=3000, price_max=100000, min_rating=100, no_identity=False,
        cap_per_keyword=10, max_details=0, keywords=["PSA10 OP01"], games=None,
        keyword_interval=0.0, headless=True, manual=False, no_dedupe=True,
        save_every=2, max_consecutive_errors=3, resume_from_json=None,
        strict_gates=False,
    )
    base.update(over)
    return types.SimpleNamespace(**base)


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(R.time, "sleep", lambda *_: None)


def _detail(url, n=1, extra=None):
    d = {"title": f"PSA10 カード{n}", "price_jpy": 10000, "condition": "新品",
         "description": "", "image_urls": ["https://x/1.jpg"], "in_stock": True,
         "is_auction": False,
         "seller_quality": {"rating_count": 200, "star": 5.0, "identity_verified": True}}
    if extra:
        d.update(extra)
    return d


@pytest.fixture
def stub_search(monkeypatch):
    """検索は3語×1件ずつ返すだけ (Chromeなし)."""
    def _collect_urls(keywords, driver, **kw):
        n = len(keywords)
        return {"urls": [f"https://jp.mercari.com/item/m{i}" for i in range(n)],
                "by_keyword": {kw: 1 for kw in keywords}, "total_raw": n}

    monkeypatch.setattr(R.MSch, "collect_multi_keyword_urls", _collect_urls)
    monkeypatch.setattr(R.MS, "create_anonymous_driver",
                        lambda headless=False: types.SimpleNamespace(quit=lambda: None))


def test_credit_error_stops_run_immediately(monkeypatch, stub_search, tmp_path):
    calls = {"n": 0}

    def _detail_fn(url):
        calls["n"] += 1
        return _detail(url, calls["n"])

    def _fake_read_slab(images, client=None, max_images=4, timeout=40):
        return {"error": "vision_api_error:BadRequestError: Error code: 400 ... "
                          "'Your credit balance is too low'"}

    monkeypatch.setattr(R.psa_slab_vision, "read_slab", _fake_read_slab)

    got = R.collect(_args(keywords=["語1", "語2", "語3"]), dump_path=tmp_path / "d.json",
                    detail_fn=_detail_fn)

    assert got["truncated"] is True
    assert got["candidates"] == []
    # 1件目で即止まる (2,3件目は処理されない = 空回りしない)
    assert calls["n"] == 1
    # 止まったURLは failed_urls に残る (= --retry-failed-from-json でそのまま拾い直せる)
    assert got["failed_urls"] == ["https://jp.mercari.com/item/m0"]


def test_credit_error_logs_dedicated_line(monkeypatch, stub_search, tmp_path):
    logged = []
    monkeypatch.setattr(R, "_log", lambda msg: logged.append(msg))

    def _detail_fn(url):
        return _detail(url)

    monkeypatch.setattr(R.psa_slab_vision, "read_slab",
                        lambda *a, **k: {"error": "insufficient_quota: billing issue"})

    R.collect(_args(), dump_path=tmp_path / "d.json", detail_fn=_detail_fn)

    assert any("⛔" in m and "残高切れ" in m for m in logged)


def test_normal_vision_error_does_not_stop_run(monkeypatch, stub_search, tmp_path):
    """残高切れ以外 (rate limit等) は1件の失敗として続ける (従来どおり)."""
    def _detail_fn(url):
        return _detail(url)

    monkeypatch.setattr(R.psa_slab_vision, "read_slab",
                        lambda *a, **k: {"error": "vision_api_error:RateLimitError: too many requests"})

    got = R.collect(_args(keywords=["語1", "語2"]), dump_path=tmp_path / "d.json",
                    detail_fn=_detail_fn)

    assert got["truncated"] is False
    assert got["collect_reject"]["vision_error"] == 2


def test_post_vision_rejected_excludes_credit_errors(monkeypatch, stub_search, tmp_path):
    """残高切れは「写真を読んだ後に外した控え」に入れない (入ると二度と読まれない)."""
    def _detail_fn(url):
        return _detail(url)

    monkeypatch.setattr(R.psa_slab_vision, "read_slab",
                        lambda *a, **k: {"error": "credit balance is too low"})

    got = R.collect(_args(), dump_path=tmp_path / "d.json", detail_fn=_detail_fn)
    assert got["post_vision_rejected"] == {}


def test_post_vision_rejected_records_genuine_mismatch(monkeypatch, stub_search, tmp_path):
    """写真を実際に読んで対象外と分かった分は控えに積む (次回は写真の前に外す)."""
    def _detail_fn(url):
        return _detail(url)

    # 読めたが鑑定番号が不鮮明 (local_gate が ng・SKIP_UNREADABLE=True なので捨てる)
    monkeypatch.setattr(R.psa_slab_vision, "read_slab",
                        lambda *a, **k: {"error": "", "cert": "", "grade": "", "label": "",
                                        "card_number": "", "year": ""})
    monkeypatch.setattr(R.psa_cert, "local_gate",
                        lambda vision, title: {"ok": False, "reason": "cert_unreadable:blur"})

    got = R.collect(_args(), dump_path=tmp_path / "d.json", detail_fn=_detail_fn)
    assert got["post_vision_rejected"] == {"https://jp.mercari.com/item/m0": "cert_unreadable"}


def test_pre_vision_excluded_skips_before_vision_call(monkeypatch, stub_search, tmp_path):
    """前回の控えに入っている URL は、写真読み(課金)の前に飛ばす."""
    read_calls = []

    def _detail_fn(url):
        return _detail(url)

    def _fake_read_slab(images, client=None, max_images=4, timeout=40):
        read_calls.append(1)
        return {"error": "", "cert": "153420191", "grade": "GEM MT 10", "label": "L",
                "card_number": "1", "year": "2024"}

    monkeypatch.setattr(R.psa_slab_vision, "read_slab", _fake_read_slab)

    got = R.collect(_args(), dump_path=tmp_path / "d.json", detail_fn=_detail_fn,
                    pre_vision_excluded={"https://jp.mercari.com/item/m0"})

    assert read_calls == []                              # 写真読みは呼んでいない
    assert got["collect_reject"]["previously_rejected"] == 1
