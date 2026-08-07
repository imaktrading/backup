"""1点もの D=○ 巡回打切り拡張の regression test (2026-08-07 revive_qty1_impl §2 後半).

依頼書 §② 「HIGH の巡回漏れを直してください」:
  旧: mercari 個人だけ D=○ skip → HIGH 上のスニダン/ラクマ/ヤフオク は素通り
  新: 1点もの全般 (メルカリ個人 / fril / snkrdunk / auctions.yahoo / paypay) を skip

期待: 巡回総量 1,139 → 474 件、 HIGH の「戻らない638件」を巡回から外し、
      visit budget を「再入荷する142件」に回す。 SHOPS は skip されず継続監視。
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
    monkeypatch.setattr(ML, "create_amazon_driver", lambda *a, **k: object())


def test_one_off_d_maru_urls_are_all_skipped(monkeypatch):
    """メルカリ個人 / fril / snkrdunk / yahoo auc の D=○ 行はすべて scrape されない。"""
    rows = [
        # ① メルカリ個人 (旧実装でも skip されていた)
        {"row_index": 10, "url": "https://jp.mercari.com/item/m12345678901",
         "item_id": "111", "title": "メルカリ個人", "current_sold": "○",
         "current_n_jpy_str": "", "err_flag_prev": ""},
        # ② ラクマ (旧実装では素通り = 巡回漏れ)
        {"row_index": 11, "url": "https://item.fril.jp/abc123",
         "item_id": "112", "title": "ラクマ", "current_sold": "○",
         "current_n_jpy_str": "", "err_flag_prev": ""},
        # ③ スニダン (旧実装では素通り)
        {"row_index": 12, "url": "https://snkrdunk.com/products/999",
         "item_id": "113", "title": "スニダン", "current_sold": "○",
         "current_n_jpy_str": "", "err_flag_prev": ""},
        # ④ ヤフオク
        {"row_index": 13, "url": "https://page.auctions.yahoo.co.jp/jp/auction/x1",
         "item_id": "114", "title": "ヤフオク", "current_sold": "○",
         "current_n_jpy_str": "", "err_flag_prev": ""},
        # ⑤ SHOPS (再入荷あり) → skip されない
        {"row_index": 14, "url": "https://jp.mercari.com/shops/product/xxx",
         "item_id": "115", "title": "SHOPS", "current_sold": "○",
         "current_n_jpy_str": "", "err_flag_prev": ""},
        # ⑥ Amazon (再入荷あり) → skip されない
        {"row_index": 15, "url": "https://amazon.co.jp/dp/B0BNHJJSZ6",
         "item_id": "116", "title": "Amazon", "current_sold": "○",
         "current_n_jpy_str": "", "err_flag_prev": ""},
    ]

    scraped_urls = []

    def _fake_check(row, **kwargs):
        scraped_urls.append(row["url"])
        return {
            "row_index": row["row_index"], "url": row["url"],
            "item_id": row.get("item_id", ""),
            "supplier": "amazon",  # any
            "is_sold": False, "raw_status": "IN_STOCK", "current_sold": "○",
            "delta": "newly_in_stock", "error": None, "price_jpy": 10000,
            "candidates_checked": 1, "current_n_jpy_str": "", "sub_results": [],
        }

    _patch_common(monkeypatch, rows, _fake_check)
    ML.process_sheet(sheet_id="dummy", sheet_label="TEST", dry_run=True)

    # 1点もの 4 種は scrape されない
    for u in [
        "https://jp.mercari.com/item/m12345678901",
        "https://item.fril.jp/abc123",
        "https://snkrdunk.com/products/999",
        "https://page.auctions.yahoo.co.jp/jp/auction/x1",
    ]:
        assert u not in scraped_urls, f"1点もの URL が scrape された (巡回漏れ): {u}"

    # 再入荷あり (SHOPS + Amazon) は scrape される
    assert "https://jp.mercari.com/shops/product/xxx" in scraped_urls
    assert "https://amazon.co.jp/dp/B0BNHJJSZ6" in scraped_urls
