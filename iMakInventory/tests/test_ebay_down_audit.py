"""Req2 regression (2026-06-10): eBay qty=0/ended × sheet D 空欄 検出.

eBay が勝手に / 手動で取下げ → eBay qty=0 or ended だが スプシ D 列未売切 のものを
「在庫あり・eBay取下げ済」 review シートに書き出す逆方向 audit。
D 列は触らない (= 自動売切化しない)。 active map 空 = eBay 取得失敗 → fail-closed。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import reverse_audit as RA  # noqa: E402


def _rows():
    # (row_index, item_id, current_sold(D), url)
    return [
        {"row_index": 2, "item_id": "100", "current_sold": "",  "url": "https://jp.mercari.com/item/m1", "title": "qty0"},
        {"row_index": 3, "item_id": "200", "current_sold": "",  "url": "https://www.amazon.co.jp/dp/B2", "title": "ended"},
        {"row_index": 4, "item_id": "300", "current_sold": "",  "url": "https://jp.mercari.com/item/m3", "title": "active正常"},
        {"row_index": 5, "item_id": "400", "current_sold": "○", "url": "https://jp.mercari.com/item/m4", "title": "売切済(対象外)"},
        {"row_index": 6, "item_id": "",    "current_sold": "",  "url": "https://jp.mercari.com/item/m5", "title": "未出品(対象外)"},
    ]


def _patch_common(monkeypatch, qty_map):
    monkeypatch.setattr(RA, "_fetch_ebay_qty_map", lambda: qty_map)
    monkeypatch.setattr(RA, "open_sheet_by_id", lambda sid: object())
    monkeypatch.setattr(RA, "get_listings_worksheet", lambda sh: object())
    monkeypatch.setattr(RA, "read_listings_rows",
                        lambda ws, only_with_url=False: _rows())


def test_detects_qty0_and_ended_excludes_active_sold_and_blank(monkeypatch):
    # 100=qty0, 300=active(qty>0), 200 は map 不在=ended
    _patch_common(monkeypatch, {"100": 0, "300": 2})
    res = RA.run_ebay_down_sheet_active_audit(
        high_sheet_id="H", low_sheet_id="L", write_sheet=False, write_log=False)

    ids = {it["item_id"]: it["ebay_state"] for it in res["items"]}
    # qty0 と ended のみ orphan、 active(300)/売切(400)/未出品("") は除外
    assert set(ids.keys()) == {"100", "200"}, ids
    assert ids["100"] == "qty=0"
    assert ids["200"].startswith("ended")
    # HIGH+LOW 両 sheet 分が二重カウントされる (test では同一 rows を 2 sheet 返す)
    assert res["orphan_count"] == 4, res["orphan_count"]


def test_empty_active_map_is_fail_closed(monkeypatch):
    _patch_common(monkeypatch, {})
    res = RA.run_ebay_down_sheet_active_audit(
        high_sheet_id="H", low_sheet_id="L", write_sheet=False, write_log=False)
    assert res["orphan_count"] == -1
    assert res["error"] == "ebay_active_map_empty"


def test_d_marked_sold_never_appears(monkeypatch):
    # 400 は D=○。 たとえ eBay qty=0 でも この audit の対象外 (reverse_audit 管轄)
    _patch_common(monkeypatch, {"100": 0, "200": 0, "300": 2, "400": 0})
    res = RA.run_ebay_down_sheet_active_audit(
        high_sheet_id="H", low_sheet_id="L", write_sheet=False, write_log=False)
    assert all(it["item_id"] != "400" for it in res["items"])
