"""mercari SHOPS D=○ skip 除外 regression (2026-06-25).

bug: mercari D=○ skip 最適化 (1点もの = 復活なし前提で売切行を完全 skip) が
mercari SHOPS (jp.mercari.com/shops/product/...) にも誤適用されていた。 SHOPS は業者出品で
restock するため、 売切→D=○ 後に源が復活しても永久 skip で検知できず D=○ が stale 化する。
iid=358705341664 (PSA10ミラーピカチュウex SHOPS) が 06-21 売切→D=○ 後に復活 (5/5 ON_SALE)
したが skip され続け、 reverse_audit で「D=○ × eBay qty>0」の偽乖離として浮上した。

修正: URL が /shops/ を含む = SHOPS は skip せず毎 cycle 再 scrape (= restock 検知)。
通常 mercari item (/item/) は従来どおり D=○ skip (1点もの最適化を維持)。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import monitor_listings as ML  # noqa: E402


class _FakeWS:
    title = "fake"
    id = 0
    row_count = 10


class _FakeSheet:
    title = "fake-sheet"


def _patch_common(monkeypatch, rows, fake_check):
    monkeypatch.setattr(ML, "open_sheet_by_id", lambda sid: _FakeSheet())
    monkeypatch.setattr(ML, "get_listings_worksheet", lambda sh, gid=0: _FakeWS())
    monkeypatch.setattr(ML, "read_listings_rows",
                        lambda ws, start_row=None, end_row=None, only_with_url=True: rows)
    monkeypatch.setattr(ML, "check_one_row_with_fallback", fake_check)
    monkeypatch.setattr(ML, "_kill_stale_scraper_chrome", lambda *a, **k: None)
    monkeypatch.setattr(ML, "create_mercari_driver", lambda *a, **k: object())


def test_mercari_shops_d_maru_is_not_skipped(monkeypatch):
    """SHOPS の D=○ 行は skip されず scrape される (restock 検知のため)。"""
    rows = [
        # 通常 mercari item + D=○ → skip される (1点もの最適化維持)
        {"row_index": 10, "url": "https://jp.mercari.com/item/m12345678901",
         "item_id": "111", "title": "通常item売切", "current_sold": "○",
         "current_n_jpy_str": ""},
        # mercari SHOPS + D=○ → skip されず scrape される
        {"row_index": 11, "url": "https://jp.mercari.com/shops/product/2JSDt2MXNwo8qctznkcHSr",
         "item_id": "358705341664", "title": "SHOPS売切→復活", "current_sold": "○",
         "current_n_jpy_str": ""},
    ]
    scraped_urls = []

    def _fake_check(row, **kwargs):
        scraped_urls.append(row["url"])
        return {
            "row_index": row["row_index"], "url": row["url"],
            "item_id": row.get("item_id", ""), "supplier": "mercari",
            "is_sold": False, "raw_status": "ON_SALE", "current_sold": "○",
            "delta": "newly_in_stock", "error": None, "price_jpy": 38280,
            "candidates_checked": 1, "current_n_jpy_str": "", "sub_results": [],
        }

    _patch_common(monkeypatch, rows, _fake_check)
    ML.process_sheet(sheet_id="dummy", sheet_label="TEST", dry_run=True)

    # 通常 item は skip (check 呼ばれない)、 SHOPS は scrape (check 呼ばれる)
    assert "https://jp.mercari.com/item/m12345678901" not in scraped_urls, \
        "通常 mercari item の D=○ skip が壊れた (1点もの最適化が無効化)"
    assert "https://jp.mercari.com/shops/product/2JSDt2MXNwo8qctznkcHSr" in scraped_urls, \
        "SHOPS の D=○ 行が skip された (restock 検知できない)"
