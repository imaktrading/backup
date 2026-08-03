"""ヨドバシ判定の URL 逆引き fallback (2026-08-03 窓口 IMPLEMENT-GO).

AI列(型番=KEY) は「未出品行に書くと orphan KEY になる」ため意図的に空の行が 34 行あり、
その行は在庫があっても永久に判定不能だった (row827/832 の実害)。snapshot は各エントリに
url を持つので、**AI列に一切書かずに** URL で逆引きして吸収する。

条件 (窓口):
  1. fail-closed を崩さない (URL でも引けなければ uncertain。在庫あり/なしに倒さない)
  2. AI列には書き込まない (orphan KEY を作らない)
  3. 型番で引ける行は従来どおり通る / URL 表記ゆれで外さない
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

pytestmark = pytest.mark.offline

SNAP = {
    "GST-B400-1AJF": {"in_stock": True, "price_jpy": 44000,
                      "url": "https://www.yodobashi.com/product/100000001006099462/"},
    "GW-8202K-2JR": {"in_stock": False, "price_jpy": 85800,
                     "url": "https://www.yodobashi.com/product/100000001009921566/"},
}
YODO_URL = "https://www.yodobashi.com/product/100000001006099462/"

import monitor_listings as _ml  # noqa: E402  (fixture の patch 前に実体を退避)
_REAL_LOAD = _ml._load_yodobashi_snapshot


@pytest.fixture(autouse=True)
def _fresh_cache(monkeypatch):
    import monitor_listings as ml
    ml._yodo_snap_cache.clear()
    monkeypatch.setattr(ml, "_load_yodobashi_snapshot", lambda: SNAP)
    yield
    ml._yodo_snap_cache.clear()


def _check(url, model=""):
    import monitor_listings as ml
    return ml._check_single_url(url, sleep_sec=0, model_number=model)


# ---------------------------------------------------------------- 既存経路 (回帰)
def test_model_lookup_still_wins():
    r = _check(YODO_URL, model="GST-B400-1AJF")
    assert r["is_sold"] is False and r["price_jpy"] == 44000 and r["error"] is None


def test_model_sold_out_still_detected():
    r = _check("https://www.yodobashi.com/product/100000001009921566/", model="GW-8202K-2JR")
    assert r["is_sold"] is True and r["raw_status"] == "yodobashi_sold"


# ---------------------------------------------------------------- URL 逆引き
def test_empty_key_falls_back_to_url():
    """★本命: AI列が空でも URL で引けて在庫ありになる (row827/832 の救済)"""
    r = _check(YODO_URL, model="")
    assert r["is_sold"] is False and r["price_jpy"] == 44000 and r["error"] is None


def test_wrong_key_falls_back_to_url():
    """AI列が別型番でも URL 側で正しく引ける (誤 KEY の巻き添えを防ぐ)"""
    r = _check(YODO_URL, model="NOT-A-MODEL")
    assert r["is_sold"] is False and r["price_jpy"] == 44000


def test_url_reverse_lookup_reports_sold():
    r = _check("https://www.yodobashi.com/product/100000001009921566/", model="")
    assert r["is_sold"] is True and r["price_jpy"] is None


@pytest.mark.parametrize("url", [
    "https://www.yodobashi.com/product/100000001006099462/",
    "https://www.yodobashi.com/product/100000001006099462",          # 末尾スラッシュ無し
    "http://www.yodobashi.com/product/100000001006099462/",          # http
    "https://yodobashi.com/product/100000001006099462/",             # www 無し
    "https://www.yodobashi.com/product/100000001006099462/?a=1#x",   # クエリ/フラグメント
    "https://www.yodobashi.com/product/100000001006099462/AAA/",     # 商品名パス付き
])
def test_url_variants_all_match(url):
    """表記ゆれで外さない (productId で突合)"""
    assert _check(url, model="")["is_sold"] is False


# ---------------------------------------------------------------- fail-closed
def test_unknown_url_stays_uncertain():
    """型番でも URL でも引けなければ従来どおり uncertain (在庫あり/なしに倒さない)"""
    r = _check("https://www.yodobashi.com/product/999999999999999/", model="")
    assert r["is_sold"] is None and "fail-closed" in (r["error"] or "")


def test_no_snapshot_stays_uncertain(monkeypatch):
    import monitor_listings as ml
    monkeypatch.setattr(ml, "_load_yodobashi_snapshot", lambda: None)
    r = _check(YODO_URL, model="GST-B400-1AJF")
    assert r["is_sold"] is None and r["error"]


def test_entry_without_in_stock_stays_uncertain(monkeypatch):
    import monitor_listings as ml
    monkeypatch.setattr(ml, "_load_yodobashi_snapshot",
                        lambda: {"X": {"in_stock": None, "url": YODO_URL}})
    ml._yodo_snap_cache.clear()
    r = _check(YODO_URL, model="")
    assert r["is_sold"] is None and "判定不能" in (r["error"] or "")


def test_snapshot_entry_without_url_is_skipped(monkeypatch):
    """url を持たないエントリは index に載せない (誤突合しない)"""
    import monitor_listings as ml
    monkeypatch.setattr(ml, "_load_yodobashi_snapshot",
                        lambda: {"X": {"in_stock": True, "price_jpy": 1}})
    ml._yodo_snap_cache.clear()
    assert _check(YODO_URL, model="")["is_sold"] is None


# ---------------------------------------------------------------- キー生成
def test_url_key_helper():
    import monitor_listings as ml
    k = ml._yodobashi_url_key
    assert k("https://www.yodobashi.com/product/100000001006099462/") == "100000001006099462"
    assert k("HTTPS://WWW.Yodobashi.com/product/100000001006099462?x=1") == "100000001006099462"
    assert k("") == ""
    # productId が無い URL は正規化 URL で突合 (誤って空キーにしない)
    assert k("https://www.yodobashi.com/category/foo/") == "yodobashi.com/category/foo"


def test_index_is_rebuilt_when_snapshot_reloads(monkeypatch):
    """snapshot を読み直したら URL index も作り直す (古い index を使い回さない)"""
    import monitor_listings as ml
    real_load = ml._load_yodobashi_snapshot.__wrapped__ \
        if hasattr(ml._load_yodobashi_snapshot, "__wrapped__") else _REAL_LOAD
    ml._yodo_snap_cache.clear()
    monkeypatch.setattr(ml, "YODOBASHI_SNAPSHOT_PATH", Path("nonexistent.json"))
    ml._yodo_snap_cache["url_index"] = {"stale": {"in_stock": True}}
    real_load()
    assert "url_index" not in ml._yodo_snap_cache
