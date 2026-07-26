"""ヨドバシ補URL 在庫snapshot lookup + M-min/延命 統合の regression test.

★ 2026-07-26 HQ依頼 (gshock_yodobashi_mmin_integration)。G-shock(LOW) の Amazon 3rd化(OOS)を
ヨドバシ補URL(新品在庫)で延命 + M=min(Amazon,ヨドバシ)。監視くんは Harvest の HTTP snapshot を
型番(AI列)で lookup するだけ (Selenium/HTTP 不要)。fail-closed: 欠損/古い/型番無 → uncertain(min対象外)。
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

YURL = "https://www.yodobashi.com/product/100000001007520427/"


@pytest.fixture
def snap(tmp_path, monkeypatch):
    """snapshot ファイルを tmp に置き、cycle キャッシュをリセットするフィクスチャ factory."""
    import monitor_listings as ml

    def _make(entries, generated_at=None, write=True):
        p = tmp_path / "yodobashi_stock_snapshot.json"
        if write:
            body = dict(entries)
            body["generated_at"] = generated_at or datetime.now().astimezone().isoformat()
            p.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
        monkeypatch.setattr(ml, "YODOBASHI_SNAPSHOT_PATH", p)
        ml._yodo_snap_cache.clear()   # cycle キャッシュをリセット
        return p
    return _make


def _row(main, slots, key):
    return {"row_index": 100, "url": main, "item_id": "356x", "title": "t",
            "current_sold": "", "key_number": key,
            "backup_url_slots": list(slots) + [None] * (5 - len(slots))}


# ============================================================================
# _check_single_url の yodobashi 分岐 (snapshot lookup)
# ============================================================================
def test_yodobashi_in_stock_with_price(snap):
    import monitor_listings as ml
    snap({"GW-8202K-2JR": {"in_stock": True, "price_jpy": 20000, "url": YURL}})
    sub = ml._check_single_url(YURL, model_number="GW-8202K-2JR")
    assert sub["supplier"] == "yodobashi"
    assert sub["is_sold"] is False       # 在庫あり (延命に使える)
    assert sub["price_jpy"] == 20000     # M-min に効く


def test_yodobashi_sold(snap):
    import monitor_listings as ml
    snap({"GW-X": {"in_stock": False, "price_jpy": None, "url": None}})
    sub = ml._check_single_url(YURL, model_number="GW-X")
    assert sub["is_sold"] is True        # 売切 (延命に使わない)
    assert sub["price_jpy"] is None


def test_yodobashi_null_is_uncertain(snap):
    """in_stock=null → uncertain (延命にも取下げにも倒さない fail-closed)."""
    import monitor_listings as ml
    snap({"GW-X": {"in_stock": None, "price_jpy": None, "url": None}})
    sub = ml._check_single_url(YURL, model_number="GW-X")
    assert sub["is_sold"] is None
    assert sub["error"] is not None


def test_yodobashi_key_missing_is_uncertain(snap):
    """snapshot に型番が無い → uncertain (min対象外)."""
    import monitor_listings as ml
    snap({"OTHER": {"in_stock": True, "price_jpy": 9000, "url": YURL}})
    sub = ml._check_single_url(YURL, model_number="GW-NOTFOUND")
    assert sub["is_sold"] is None
    assert sub["price_jpy"] is None


def test_yodobashi_stale_snapshot_is_uncertain(snap):
    """generated_at が古すぎ → 全 lookup uncertain (fail-closed)."""
    import monitor_listings as ml
    old = (datetime.now().astimezone() - timedelta(hours=13)).isoformat()
    snap({"GW-X": {"in_stock": True, "price_jpy": 20000, "url": YURL}}, generated_at=old)
    sub = ml._check_single_url(YURL, model_number="GW-X")
    assert sub["is_sold"] is None        # 12h 超 → 使わない


def test_yodobashi_missing_file_is_uncertain(snap, tmp_path, monkeypatch):
    import monitor_listings as ml
    monkeypatch.setattr(ml, "YODOBASHI_SNAPSHOT_PATH", tmp_path / "nope.json")
    ml._yodo_snap_cache.clear()
    sub = ml._check_single_url(YURL, model_number="GW-X")
    assert sub["is_sold"] is None


# ============================================================================
# 統合: Amazon(主)3rd化 + ヨドバシ補 の 延命 + M-min
# ============================================================================
def _stub_amazon_yodo(amazon_sold, yodo_key):
    """主=amazon (sold 可変) + 補=yodobashi (実 lookup) の混在 stub。"""
    import monitor_listings as ml
    real = ml._check_single_url

    def _f(url, sleep_sec=0, mercari_driver=None, amazon_driver=None, model_number=""):
        if "amazon" in url:
            return {"url": url, "supplier": "amazon",
                    "is_sold": amazon_sold, "raw_status": "x",
                    "error": None if amazon_sold is not None else "e",
                    "price_jpy": (None if amazon_sold else 30000), "points_jpy": None}
        return real(url, sleep_sec, mercari_driver, amazon_driver, model_number=model_number)
    return _f


def test_amazon_3rd_yodo_alive_extends_and_min(snap):
    """★主=Amazon 3rd化(OOS) + ヨドバシ補=在庫2万 → 延命(is_sold=False) + M=20000."""
    import monitor_listings as ml
    snap({"GW-8202K-2JR": {"in_stock": True, "price_jpy": 20000, "url": YURL}})
    row = _row("https://www.amazon.co.jp/dp/B0X", [YURL], "GW-8202K-2JR")
    with patch("monitor_listings._check_single_url",
               side_effect=_stub_amazon_yodo(amazon_sold=True, yodo_key="GW-8202K-2JR")):
        r = ml.check_one_row_with_fallback(row)
    assert r["is_sold"] is False       # ★延命 (Amazon OOS でもヨドバシ在庫)
    assert r["price_jpy"] == 20000     # ★M=ヨドバシ価格


def test_amazon_alive_cheaper_than_yodo_min(snap):
    """主=Amazon 在庫3万 + ヨドバシ補=在庫2万 → 延命 + M=20000 (最安=ヨドバシ)."""
    import monitor_listings as ml
    snap({"GW-8202K-2JR": {"in_stock": True, "price_jpy": 20000, "url": YURL}})
    row = _row("https://www.amazon.co.jp/dp/B0X", [YURL], "GW-8202K-2JR")
    with patch("monitor_listings._check_single_url",
               side_effect=_stub_amazon_yodo(amazon_sold=False, yodo_key="GW-8202K-2JR")):
        r = ml.check_one_row_with_fallback(row)
    assert r["is_sold"] is False
    assert r["price_jpy"] == 20000     # min(Amazon 30000, ヨドバシ 20000)


def test_both_oos_takedown(snap):
    """主=Amazon OOS + ヨドバシ補=売切 → 全売切 → is_sold=True (D=○)."""
    import monitor_listings as ml
    snap({"GW-8202K-2JR": {"in_stock": False, "price_jpy": None, "url": None}})
    row = _row("https://www.amazon.co.jp/dp/B0X", [YURL], "GW-8202K-2JR")
    with patch("monitor_listings._check_single_url",
               side_effect=_stub_amazon_yodo(amazon_sold=True, yodo_key="GW-8202K-2JR")):
        r = ml.check_one_row_with_fallback(row)
    assert r["is_sold"] is True        # 全仕入元 OOS → 取下げ


def test_amazon_oos_yodo_uncertain_not_takedown(snap):
    """主=Amazon OOS + ヨドバシ補=判定不能(null) → uncertain (誤 D=○ にしない fail-closed)."""
    import monitor_listings as ml
    snap({"GW-8202K-2JR": {"in_stock": None, "price_jpy": None, "url": None}})
    row = _row("https://www.amazon.co.jp/dp/B0X", [YURL], "GW-8202K-2JR")
    with patch("monitor_listings._check_single_url",
               side_effect=_stub_amazon_yodo(amazon_sold=True, yodo_key="GW-8202K-2JR")):
        r = ml.check_one_row_with_fallback(row)
    assert r["is_sold"] is None        # uncertain → 取下げ skip (fail-closed)
