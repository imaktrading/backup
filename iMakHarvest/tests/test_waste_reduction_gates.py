"""tests/test_waste_reduction_gates - 無駄読み防止 (2026-10-17 HQ依頼 B-20261017-007).

写真読み(課金API)の前に、 タイトルだけで分かる「PSA10 以外」を落とす門と、
月の上限($45)で読み取りを止める門を検証する。 どちらも Vision を一度も
呼ばずに判定できることを `psa_slab_vision.read_slab` を "呼んだら即失敗" にして確認する。
"""
from __future__ import annotations

import types
from collections import defaultdict

import pytest

import run_harvest_mercari_psa10 as R

pytestmark = pytest.mark.offline


def _rej(**over):
    d = defaultdict(int)
    d.update(over)
    return d


def _args(**over):
    base = dict(
        strict_gates=True, cost_cfg={"max_jpy": 1_000_000}, card_limits={},
        min_rating=100, no_identity=False, monthly_cap_usd=0, max_vision=0,
    )
    base.update(over)
    return types.SimpleNamespace(**base)


def _detail(title="PSA10 ピカチュウ 151/165", price_jpy=10000):
    return {
        "title": title, "price_jpy": price_jpy, "condition": "新品",
        "description": "", "image_urls": ["https://x/1.jpg"],
        "seller_quality": {"rating_count": 500, "star": 5.0, "identity_verified": True},
        "in_stock": True, "is_auction": False,
    }


def _boom_vision(*a, **k):
    raise AssertionError("Vision を呼んではいけない (タイトル/月次上限で先に落ちるはず)")


def test_title_with_other_grade_rejected_before_vision(monkeypatch):
    """タイトルに PSA9 等が明記されている分は写真読みの前に落とす."""
    monkeypatch.setattr(R.psa_slab_vision, "read_slab", _boom_vision)
    rej = {"title_not_psa10": 0}

    def _detail_fn(url):
        return _detail(title="PSA9 ピカチュウ 151/165")

    got = R._process_one("https://x/1", lambda: None, _args(), {"urls": set(), "certs": set()},
                         rej, [], detail_fn=_detail_fn)
    assert got is None
    assert rej["title_not_psa10"] == 1


def test_title_without_psa10_mention_still_reaches_vision(monkeypatch):
    """タイトルに PSA10 と書いていないだけ(確証が無いだけ)は pre-vision で落とさない
    (= looks_like_psa10 でなく contradicts_psa10 を使っている確認。 recall を減らさない)."""
    called = {"n": 0}

    def _fake_read_slab(images):
        called["n"] += 1
        return {"cert": "123", "grade": "GEM MT 10", "label": "L", "card_number": "1",
                "year": "2024", "error": "", "input_tokens": 10, "output_tokens": 10}

    monkeypatch.setattr(R.psa_slab_vision, "read_slab", _fake_read_slab)
    monkeypatch.setattr(R.psa_cert, "local_gate", lambda vision, title: {"ok": True})
    monkeypatch.setattr(R.psa_grade_gate, "looks_like_psa10", lambda **kw: True)

    def _detail_fn(url):
        return _detail(title="美品 スラブ入り ピカチュウ")  # PSA10 と書いていない

    R._process_one("https://x/1", lambda: None, _args(), {"urls": set(), "certs": set()},
                   _rej(), [], detail_fn=_detail_fn, usage={"calls": 0})
    assert called["n"] == 1   # Vision は呼ばれた (pre-vision門で誤って落としていない)


def test_monthly_cap_reached_blocks_before_vision(monkeypatch):
    """今月すでに上限近くまで使っていたら、 この走行の最初から Vision を呼ばない."""
    monkeypatch.setattr(R.psa_slab_vision, "read_slab", _boom_vision)
    args = _args(monthly_cap_usd=45.0)
    args._prior_month_vision_cost = 45.0  # 既に上限ちょうど
    rej = _rej()
    usage = {"calls": 0, "input_tokens": 0, "output_tokens": 0}

    got = R._process_one("https://x/1", lambda: None, args, {"urls": set(), "certs": set()},
                         rej, [], detail_fn=lambda u: _detail(), usage=usage)
    assert got is None
    assert rej["monthly_cap_reached"] == 1


def test_month_to_date_vision_cost_sums_only_current_month(tmp_path, monkeypatch):
    log = tmp_path / "vision_cost_log.csv"
    log.write_text(
        "timestamp,calls,input_tokens,output_tokens,est_usd,truncated\n"
        "2026-09-30T23:00:00,10,1000,1000,0.5000,False\n"   # 前月 (無視される)
        "2026-10-01T00:00:00,10,1000,1000,1.2500,False\n"
        "2026-10-16T07:57:33,400,1362949,23267,1.4793,True\n",
        encoding="utf-8")
    monkeypatch.setattr(R, "VISION_COST_LOG", log)
    from datetime import datetime
    total = R.month_to_date_vision_cost(now=datetime(2026, 10, 17))
    assert total == pytest.approx(1.2500 + 1.4793)


def test_run_summary_cost_line_logged_even_with_zero_vision_calls(monkeypatch, tmp_path):
    """読んだ0件でも「💰 写真読み: ...」の1行を出す (0件でも出す原則)."""
    logged = []
    monkeypatch.setattr(R, "_log", lambda m: logged.append(m))
    monkeypatch.setattr(R, "VISION_COST_LOG", tmp_path / "vision_cost_log.csv")
    monkeypatch.setattr(R.MS, "create_anonymous_driver",
                        lambda headless=False: types.SimpleNamespace(quit=lambda: None))
    monkeypatch.setattr(R.MSch, "collect_multi_keyword_urls",
                        lambda *a, **k: {"urls": [], "by_keyword": {}, "total_raw": 0})

    args = types.SimpleNamespace(
        price_min=3000, price_max=100000, min_rating=100, no_identity=False,
        cap_per_keyword=10, max_details=0, keywords=["PSA10 x"], games=None,
        keyword_interval=0.0, headless=True, manual=False, no_dedupe=True,
        save_every=10, max_consecutive_errors=3, resume_from_json=None,
    )
    R.collect(args, dump_path=tmp_path / "d.json")
    assert any(m.startswith("💰 写真読み: 読んだ0件") for m in logged)
