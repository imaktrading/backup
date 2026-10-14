"""QUICK (急ぐ出品だけをすぐ見る短い巡回、2026-10-14 B-20261014-007)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import quick_watch as Q  # noqa: E402


def test_pending_rows_only_unprocessed():
    vals = [Q.QUICK_HEADER,
            ["820045156348", "補を書いた", "2026-10-14 10:00", "出品くん", "", "", ""],
            ["820110211566", "急ぐ", "2026-10-14 10:01", "出品くん", "済", "2026-10-14 10:05", "在庫あり"],
            ["", "", "", "", "", "", ""],
            [" 358853881132 ", "補を書いた"]]                       # 列が足りない行・空白
    from datetime import datetime
    got = Q.pending_rows(vals, now=datetime(2026, 10, 14, 10, 30))      # 急ぐの済は 25 分前 = まだ
    assert got == [(2, "820045156348", False), (5, "358853881132", False)]


def test_urgent_rows_repeat_hourly_and_dedupe():
    from datetime import datetime
    now = datetime(2026, 10, 14, 12, 0)
    vals = [Q.QUICK_HEADER,
            ["A", "急ぐ", "2026-10-14 10:27", "出品くん", "済", "2026-10-14 11:10:00", ""],   # 50 分前 → まだ
            ["B", "急ぐ", "2026-10-14 10:27", "出品くん", "済", "2026-10-14 10:50:00", ""],   # 70 分前 → また見る
            ["C", "補を書いた", "2026-10-14 08:00", "出品くん", "済", "2026-10-14 09:00:00", ""],  # 急ぐでない済 → 見ない
            ["B", "急ぐ", "2026-10-14 10:27", "出品くん", "", "", ""],                          # 同じ itemID の新しい行
            ["D", "急ぐ", "2026-10-14 10:27", "出品くん", "", "", ""]]
    got = Q.pending_rows(vals, now=now)
    assert got == [(5, "B", True), (6, "D", True)]


def test_result_text():
    assert Q.result_text(None)[0] == "シートに無い"
    assert Q.result_text({"is_sold": False, "price_jpy": 13000}) == ("済", "在庫あり M=¥13,000")
    assert "売切" in Q.result_text({"is_sold": True, "raw_status": "all_sold (2/2)"})[1]
    assert "次の HIGH" in Q.result_text({"is_sold": None, "error": "timeout"})[1]


def test_quick_is_a_signal_label():
    import cycle_signal as S
    assert S.LATEST_CELL["QUICK"] == "E1"
    assert S.decide("QUICK", {"ok": True}) == (True, "")


def test_only_item_ids_and_api_only(monkeypatch, tmp_path):
    """指定の itemID の行だけを、Chrome を立てずに読む."""
    import monitor_listings as m
    monkeypatch.setattr(m, "SUPPLY_PRICES_FILE", tmp_path / "supply_prices.json")   # 本番の控えを汚さない
    from unittest.mock import MagicMock
    rows = [{"row_index": 2, "item_id": "A1", "url": "https://jp.mercari.com/item/m1", "title": "PSA10 a",
             "backup_url_slots": [None] * 5, "current_sold": "", "current_m_jpy_str": "1000"},
            {"row_index": 3, "item_id": "B2", "url": "https://jp.mercari.com/item/m2", "title": "PSA10 b",
             "backup_url_slots": [None] * 5, "current_sold": "", "current_m_jpy_str": "1000"}]
    monkeypatch.setattr(m, "open_sheet_by_id", lambda *_a, **_k: MagicMock(title="sh"))
    monkeypatch.setattr(m, "get_listings_worksheet", lambda *_a, **_k: MagicMock(title="ws", id=1, row_count=3))
    monkeypatch.setattr(m, "ensure_listings_err_header", lambda *_a, **_k: False)
    monkeypatch.setattr(m, "read_listings_rows", lambda *_a, **_k: rows)
    monkeypatch.setattr(m, "update_listings_sold_marks", lambda *_a, **_k: {"updated": 1})
    monkeypatch.setattr(m, "append_pending_revise", lambda *_a, **_k: None)
    monkeypatch.setattr(m.time, "sleep", lambda *_a, **_k: None)
    def no_chrome(*_a, **_k):
        raise AssertionError("Chrome を立ててはいけない")
    monkeypatch.setattr(m, "create_mercari_driver", no_chrome)
    monkeypatch.setattr(m, "create_amazon_driver", no_chrome)
    monkeypatch.setattr(m, "_kill_stale_scraper_chrome", no_chrome)
    seen = []
    def fake_fetch(url, driver=None, use_selenium_fallback=True):
        seen.append(url)
        assert driver is None
        return {"name": "PSA10 a", "status": "ON_SALE", "skus": [{"in_stock": True, "price_jpy": 1100}]}
    monkeypatch.setattr(m, "fetch_mercari", fake_fetch)
    st = m.process_sheet(sheet_id="x", sheet_label="QUICK_TEST", rows_filter="listed",
                         only_item_ids={"A1"}, api_only=True, sleep_sec=0)
    assert seen == ["https://jp.mercari.com/item/m1"]
    assert st["processed"] == 1 and st["item_results"]["A1"]["is_sold"] is False
    m._API_ONLY = False
    import supply_guard as G
    G.STREAK_READONLY = False
    for f in list(m.DECISION_LOG_DIR.glob("*QUICK_TEST*")) + list((m.SCRIPT_DIR / "logs").glob("*QUICK_TEST*")):
        f.unlink(missing_ok=True)              # 試験の跡を本番の記録に残さない


# ── 一番安い 1 本だけ (B-20261014-010) ──────────────────────────────────
def _setup_cheap(monkeypatch, pages):
    import monitor_listings as m
    import supply_guard as G
    monkeypatch.setattr(G, "STREAK_READONLY", True)
    monkeypatch.setattr(G, "record_review", lambda *a, **k: None)
    read = []
    def fake(url, driver=None, use_selenium_fallback=True):
        read.append(url)
        ok, price = pages[url]
        return {"name": "PSA10 x", "status": "ON_SALE" if ok else "SOLD_OUT",
                "skus": [{"in_stock": ok, "price_jpy": price if ok else None}]}
    monkeypatch.setattr(m, "fetch_mercari", fake)
    monkeypatch.setattr(m.time, "sleep", lambda *_a, **_k: None)
    return m, read


U = ["https://jp.mercari.com/item/m%d" % i for i in range(1, 4)]
ROW = {"row_index": 9, "item_id": "X", "title": "PSA10 x", "url": U[0],
       "backup_url_slots": [U[1], U[2], None, None, None], "current_m_jpy_str": "10000"}
KNOWN = [{"url": U[0], "price": 15000, "alive": True}, {"url": U[1], "price": 10000, "alive": True},
         {"url": U[2], "price": 12000, "alive": True}]


def test_cheapest_alive_reads_one(monkeypatch):
    m, read = _setup_cheap(monkeypatch, {U[1]: (True, 10000)})
    r = m.check_one_row_cheapest(ROW, KNOWN, sleep_sec=0)
    assert read == [U[1]] and r["is_sold"] is False and r["price_jpy"] == 10000
    assert "backup_slot_results" not in r                 # 消込はしない


def test_cheapest_sold_goes_to_next(monkeypatch):
    m, read = _setup_cheap(monkeypatch, {U[1]: (False, None), U[2]: (True, 12000)})
    r = m.check_one_row_cheapest(ROW, KNOWN, sleep_sec=0)
    assert read == [U[1], U[2]] and r["is_sold"] is False and r["price_jpy"] == 12000


def test_cheapest_price_rose_reads_next_and_takes_min(monkeypatch):
    m, read = _setup_cheap(monkeypatch, {U[1]: (True, 13000), U[2]: (True, 12000)})
    r = m.check_one_row_cheapest(ROW, KNOWN, sleep_sec=0)
    assert read == [U[1], U[2]] and r["price_jpy"] == 12000


def test_all_sold_is_sold(monkeypatch):
    m, read = _setup_cheap(monkeypatch, {U[1]: (False, None), U[2]: (False, None), U[0]: (False, None)})
    r = m.check_one_row_cheapest(ROW, KNOWN, sleep_sec=0)
    assert len(read) == 3 and r["is_sold"] is True


def test_cheapest_order_puts_unknown_last():
    import monitor_listings as m
    known = [{"url": U[0], "price": 15000, "alive": True}, {"url": U[2], "price": None, "alive": False}]
    assert m.cheapest_order(ROW, known) == [U[0], U[1], U[2]]


def test_only_latest_urgent_batch_is_rechecked():
    """出品くんの直近の回に無い itemID (急ぐでなくなった) は 55 分の見直しから外す."""
    from datetime import datetime
    now = datetime(2026, 10, 14, 13, 0)
    vals = [Q.QUICK_HEADER,
            ["OLD", "急ぐ", "2026-10-14 10:27", "出品くん", "済", "2026-10-14 10:40:00", ""],   # 前の回だけ
            ["KEEP", "急ぐ", "2026-10-14 10:27", "出品くん", "済", "2026-10-14 10:40:00", ""],
            ["KEEP", "急ぐ", "2026-10-14 12:25", "出品くん", "済", "2026-10-14 11:50:00", ""],   # 直近の回にもある
            ["NEW2", "急ぐ", "2026-10-14 12:31", "出品くん", "済", "2026-10-14 11:50:00", ""]]   # 同じ回 (6 分差)
    got = Q.pending_rows(vals, now=now)
    assert [g[1] for g in got] == ["KEEP", "NEW2"]
