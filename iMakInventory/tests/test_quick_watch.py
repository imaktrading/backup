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
    assert Q.pending_rows(vals) == [(2, "820045156348"), (5, "358853881132")]


def test_result_text():
    assert Q.result_text(None)[0] == "シートに無い"
    assert Q.result_text({"is_sold": False, "price_jpy": 13000}) == ("済", "在庫あり M=¥13,000")
    assert "売切" in Q.result_text({"is_sold": True, "raw_status": "all_sold (2/2)"})[1]
    assert "次の HIGH" in Q.result_text({"is_sold": None, "error": "timeout"})[1]


def test_quick_is_a_signal_label():
    import cycle_signal as S
    assert S.LATEST_CELL["QUICK"] == "E1"
    assert S.decide("QUICK", {"ok": True}) == (True, "")


def test_only_item_ids_and_api_only(monkeypatch):
    """指定の itemID の行だけを、Chrome を立てずに読む."""
    import monitor_listings as m
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
