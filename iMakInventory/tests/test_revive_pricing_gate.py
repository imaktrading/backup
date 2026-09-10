"""復活に採算チェックを掛けない (2026-09-10 ユーザー判断で廃止) の regression test.

旧: 2026-08-07 に「推奨価格 > 現在価格 なら復活させず価格改定待ち」の gate を入れていた。
廃止理由:
- 監視くんは価格を持たない (4者の役割表 2026-08-22: 監視くん = 仕入元がまだ買えるか)
- 採算計算は 2026-05-01 のコピーの pricing_engine で、本元 V9 とずれていた
  (為替 159.245 vs 153.762 / 一番くじ送料 ¥2,500 vs ¥4,000)
- 値段は Revise が毎日 V9 に合わせるので、二重に持つ必要がない

ここでは「値段・カテゴリ・仕入値の有無で復活を止めない」ことと、
値段と無関係な安全チェック (既に復活済み) は残っていることを固定する。
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import ebay_actions.revive_csv_generator as RG  # noqa: E402


def _valid_row(iid, category="G-SHOCK", cur_m="10000", price="10000"):
    return {
        "row_index": 100,
        "url": "https://amazon.co.jp/dp/B00000000X",
        "item_id": iid,
        "title": iid,
        "current_sold": "",
        "err_flag_prev": "",
        "checked_at": "2026/09/10 12:00:00",
        "sheet_label": "HIGH",
        "key_number": "",
        "category": category,
        "price": price,
        "current_m_jpy_str": cur_m,
    }


def _run(candidates, fetch):
    return RG.apply_gates(
        candidates=candidates,
        sheet_key_maps={"HIGH": {}},
        cycle_started_at=datetime(2026, 9, 10, 11, 0, 0),
        active_qty_map={},
        fetch_price_fn=fetch,
    )


def test_pricing_gate_is_gone():
    """採算チェックの関数と価格カテゴリ表は 監視くんに残っていない."""
    import sheet_updater
    assert not hasattr(RG, "check_pricing_gate")
    assert not hasattr(RG, "_load_pricing_engine")
    assert not hasattr(sheet_updater, "resolve_pricing_category")
    assert not hasattr(sheet_updater, "CAT_SHEET_TO_PRICING")


def test_low_price_unmapped_category_or_no_cost_do_not_block_revive():
    """値段が安い / カテゴリが価格表に無い / 仕入値が空 でも 復活は止めない."""
    cands = [
        _valid_row("IID_CHEAP_001"),                           # eBay 価格が安い
        _valid_row("IID_BAG_002", category="バッグ"),          # 旧: skip_no_category
        _valid_row("IID_NOCOST_003", cur_m="", price=""),      # 旧: skip_no_cost
    ]
    allowed, deferred, price_hold = _run(cands, lambda iid: (1.00, 0))
    assert {c["item_id"] for c in allowed} == {"IID_CHEAP_001", "IID_BAG_002", "IID_NOCOST_003"}
    assert deferred == []
    assert price_hold == []                                    # 価格改定待ちは もう作らない


def test_already_live_is_still_skipped():
    """値段と無関係な安全チェック (eBay が既に qty>0) は残す."""
    allowed, deferred, _ = _run([_valid_row("IID_LIVE_001")], lambda iid: (99.0, 1))
    assert allowed == []
    assert deferred[0]["skip_reason"] == "ebay_already_qty_1"
