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
    """型番でも URL でも引けない → uncertain (min対象外).

    ★ 2026-08-03: URL 逆引き fallback 追加により「型番が無い」だけでは uncertain にならない
    (同じ URL のエントリがあれば引ける = 本 fallback の目的)。uncertain になるのは
    **型番も URL も当たらない**時だけ、に期待値を更新。URL が当たるケースは
    tests/test_yodobashi_url_lookup.py が担保する。
    """
    import monitor_listings as ml
    snap({"OTHER": {"in_stock": True, "price_jpy": 9000,
                    "url": "https://www.yodobashi.com/product/999999999999999/"}})
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


# ============================================================================
# URL 逆引き fallback (2026-08-03 追加)
#   窓口回答 `2026-08-03_yodobashi_url_reverse_lookup_response.md` の条件:
#     - 型番で引ける行は従来どおり通ること
#     - AI空+URL一致で引けること (=orphan KEY を作らずコード側で吸収)
#     - 両方失敗で uncertain になること (fail-closed)
#     - URL の表記ゆれ (末尾スラッシュ等) で外さないこと
# ============================================================================
def test_url_fallback_hit_when_key_empty(snap):
    """AI列(型番) 空 でも 補URL が snapshot と一致すれば in_stock で拾える."""
    import monitor_listings as ml
    snap({"GST-B400-1AJF": {"in_stock": True, "price_jpy": 44000, "url": YURL}})
    sub = ml._check_single_url(YURL, model_number="")     # ← 型番なし
    assert sub["supplier"] == "yodobashi"
    assert sub["is_sold"] is False
    assert sub["price_jpy"] == 44000
    assert sub["error"] is None


def test_url_fallback_hit_when_key_wrong(snap):
    """AI列(型番) が snapshot に無い型番でも 補URL が一致すれば拾える (AI列に依存しない)."""
    import monitor_listings as ml
    snap({"GST-B400-1AJF": {"in_stock": True, "price_jpy": 44000, "url": YURL}})
    sub = ml._check_single_url(YURL, model_number="WRONG-KEY-9999")
    assert sub["is_sold"] is False
    assert sub["price_jpy"] == 44000


def test_url_fallback_sold(snap):
    """URL 逆引きでも in_stock=False は正しく sold に落とす (延命扱いにしない)."""
    import monitor_listings as ml
    snap({"GST-X": {"in_stock": False, "price_jpy": None, "url": YURL}})
    sub = ml._check_single_url(YURL, model_number="")
    assert sub["is_sold"] is True
    assert sub["price_jpy"] is None


def test_url_fallback_none_is_uncertain(snap):
    """URL 逆引きヒット + in_stock=None → uncertain (fail-closed)."""
    import monitor_listings as ml
    snap({"GST-X": {"in_stock": None, "price_jpy": None, "url": YURL}})
    sub = ml._check_single_url(YURL, model_number="")
    assert sub["is_sold"] is None
    assert sub["error"] is not None


def test_url_fallback_miss_is_uncertain(snap):
    """AI列も URL も snapshot に無い → uncertain (fail-closed / 誤 sold にも 誤 in_stock にも倒さない)."""
    import monitor_listings as ml
    snap({"GST-X": {"in_stock": True, "price_jpy": 44000,
                    "url": "https://www.yodobashi.com/product/999999999999999999/"}})
    sub = ml._check_single_url(YURL, model_number="")     # URL も 型番も miss
    assert sub["is_sold"] is None
    assert sub["price_jpy"] is None
    assert sub["error"] is not None


def test_key_hit_still_wins_over_url(snap):
    """型番で引ける行は従来どおり通る (URL 逆引きは fallback、上書きしない)."""
    import monitor_listings as ml
    # 同じ URL に対して 型番 A は 在庫あり 44000、型番 B は 在庫あり 99999
    # 呼出は 型番 A なので 44000 が採用されるべき (URL 逆引きに落ちて B を拾わない)
    snap({
        "MATCHED-KEY":    {"in_stock": True, "price_jpy": 44000, "url": YURL},
        "OTHER-BUT-SAME": {"in_stock": True, "price_jpy": 99999, "url": YURL},
    })
    sub = ml._check_single_url(YURL, model_number="MATCHED-KEY")
    assert sub["price_jpy"] == 44000


def test_url_fallback_ignores_trailing_slash(snap):
    """末尾スラッシュ有無で外さない (行の URL は無、snapshot 側は有)."""
    import monitor_listings as ml
    snap({"K": {"in_stock": True, "price_jpy": 44000,
                "url": "https://www.yodobashi.com/product/100000001006099462/"}})
    sub = ml._check_single_url(
        "https://www.yodobashi.com/product/100000001006099462",   # 末尾 / 無
        model_number="",
    )
    assert sub["is_sold"] is False
    assert sub["price_jpy"] == 44000


def test_url_fallback_ignores_query_and_case(snap):
    """クエリ・fragment・大小文字差で外さない (canonical productId で突合)."""
    import monitor_listings as ml
    snap({"K": {"in_stock": True, "price_jpy": 44000,
                "url": "https://www.yodobashi.com/product/100000001006099462/"}})
    sub = ml._check_single_url(
        "HTTPS://WWW.yodobashi.com/product/100000001006099462/?utm_source=x#frag",
        model_number="",
    )
    assert sub["is_sold"] is False
    assert sub["price_jpy"] == 44000


def test_url_fallback_no_productid_no_hit(snap):
    """productId を含まない URL は逆引き対象外 (誤突合を作らない)."""
    import monitor_listings as ml
    snap({"K": {"in_stock": True, "price_jpy": 44000,
                "url": "https://www.yodobashi.com/product/100000001006099462/"}})
    sub = ml._check_single_url(
        "https://www.yodobashi.com/category/gshock/",   # productId 無し
        model_number="",
    )
    assert sub["is_sold"] is None
    assert sub["error"] is not None


def test_url_index_rebuilt_when_snapshot_reloads(snap):
    """snapshot が切り替わったら URL 逆引き index も作り直す (古い index で判定しない)."""
    import monitor_listings as ml
    URL_OLD = "https://www.yodobashi.com/product/100000001000000001/"
    URL_NEW = "https://www.yodobashi.com/product/100000001000000002/"
    snap({"K1": {"in_stock": True,  "price_jpy": 1000, "url": URL_OLD}})
    ml._check_single_url(URL_OLD, model_number="")   # index を張る
    snap({"K2": {"in_stock": True,  "price_jpy": 2000, "url": URL_NEW}})
    # 古い URL は もう snapshot に無い → uncertain (旧 index を使い回さない)
    old = ml._check_single_url(URL_OLD, model_number="")
    assert old["is_sold"] is None
    # 新しい URL は 拾える
    new = ml._check_single_url(URL_NEW, model_number="")
    assert new["is_sold"] is False
    assert new["price_jpy"] == 2000


def test_ai_column_never_written(snap):
    """★orphan KEY 防止: URL 逆引きは AI列 (row['key_number']) を書き換えない.

    (実装は _check_single_url に閉じているので row dict は不変のはず。回帰の門番として明示 assert。)
    """
    import monitor_listings as ml
    snap({"GST-B400-1AJF": {"in_stock": True, "price_jpy": 44000, "url": YURL}})
    row = _row("https://www.amazon.co.jp/dp/B0X", [YURL], "")   # AI列 空
    original_key = row["key_number"]
    with patch("monitor_listings._check_single_url",
               side_effect=_stub_amazon_yodo(amazon_sold=True, yodo_key="")):
        r = ml.check_one_row_with_fallback(row)
    assert row["key_number"] == original_key == ""     # 触っていない
    assert "key_number" not in r                       # 結果 dict にも書き戻していない
    assert r["is_sold"] is False                       # かつ URL 逆引きで救済できている
    assert r["price_jpy"] == 44000
