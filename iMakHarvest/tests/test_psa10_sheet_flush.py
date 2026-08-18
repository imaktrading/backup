"""tests/test_psa10_sheet_flush - 走行中に中間スプシへ途中書込する.

2026-08-18 user 指示「途中で保存してよ」。 最後にまとめて書くと、 プロセスが落ちた時に
その走行の成果が 1 行もスプシに残らない (JSON には残るが、 人が見るのはスプシ)。
"""
from __future__ import annotations

import types

import pytest

import run_harvest_mercari_psa10 as R

pytestmark = pytest.mark.offline


def _args(**kw):
    base = dict(price_min=3000, price_max=100000, min_rating=100, no_identity=False,
                cap_per_keyword=10, max_details=0, keywords=["k"], games=None,
                keyword_interval=0.0, headless=True, manual=False, no_dedupe=True,
                save_every=2, sheet_every=2, max_consecutive_errors=3,
                resume_from_json=None, retry_from_json=None, label="psa10",
                dry_run=False)
    base.update(kw)
    return types.SimpleNamespace(**base)


def _candidate(url, cert="123456789"):
    return {"url": url, "title": "PSA10 ワンピース ルフィ", "price_jpy": 1000,
            "condition": "", "description": "", "image_urls": [],
            "vision": {"cert": cert, "label": "ONE PIECE"}, "cert_readable": True}


@pytest.fixture
def _stub(monkeypatch):
    monkeypatch.setattr(R.time, "sleep", lambda *_: None)
    monkeypatch.setattr(R.MS, "create_anonymous_driver",
                        lambda headless=False: types.SimpleNamespace(quit=lambda: None))
    monkeypatch.setattr(R, "_process_one",
                        lambda url, *a, **k: _candidate(url))


def test_flush_is_called_during_run(_stub):
    """save_every ごとに スプシへ書きに行く (最後の1回だけではない)."""
    calls = []

    def on_flush(new_c, new_u):
        calls.append((len(new_c), len(new_u)))
        return len(new_c), len(new_u)

    urls = [f"https://jp.mercari.com/item/m{i}" for i in range(1, 7)]
    R.collect(_args(), urls_override=urls, on_flush=on_flush)
    assert len(calls) >= 2, calls
    assert sum(c for c, _ in calls) == 6  # 全部が いずれかの回で書かれる


def test_flush_never_sends_the_same_item_twice(_stub):
    seen = []

    def on_flush(new_c, new_u):
        seen.extend(c["url"] for c in new_c)
        return len(new_c), 0

    urls = [f"https://jp.mercari.com/item/m{i}" for i in range(1, 7)]
    R.collect(_args(), urls_override=urls, on_flush=on_flush)
    assert len(seen) == len(set(seen)) == 6


def test_no_flush_callback_is_ok(_stub):
    """on_flush 無し (= 従来動作) でも走行は変わらない."""
    urls = [f"https://jp.mercari.com/item/m{i}" for i in range(1, 4)]
    payload = R.collect(_args(), urls_override=urls)
    assert len(payload["candidates"]) == 3
