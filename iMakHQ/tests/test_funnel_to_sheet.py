# -*- coding: utf-8 -*-
"""Stage1: ファネル全結果のスプシ集約 (listing_funnel.write_funnel_to_sheet) の純粋部分。"""
import importlib.util
import os

_LF = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "tools", "listing_funnel.py"))


def _load():
    spec = importlib.util.spec_from_file_location("listing_funnel_t", _LF)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_funnel_vals_matches_cols_length():
    lf = _load()
    r = {"item_id": "1", "title": "T", "site": "US", "category": "Wristwatches", "price": 100,
         "trend_price": 90, "qty": 1, "sold_qty": 0, "sales90": 0, "watch": 2,
         "impr": 12.34, "ctr": 0.0123, "photos": 3, "keywords": 2, "relist_status": ""}
    vals = lf._funnel_vals(r)
    assert len(vals) == len(lf.FUNNEL_COLS)        # 列数一致
    assert vals[0] == "1" and vals[1] == "T"
    assert vals[10] == 12.3                          # impr 丸め
    assert vals[11] == 1.23                          # ctr% = ctr*100 丸め
    assert vals[-1] == "https://www.ebay.com/itm/1"  # ebay_url 補完


def test_funnel_buckets_are_nine():
    lf = _load()
    keys = [k for k, _ in lf.FUNNEL_BUCKETS]
    for must in ("NO_SEARCH", "NO_CLICK", "NO_CONVERT", "OVERPRICED", "NEW_WAIT",
                 "RELIST", "RESTOCK", "CULL", "DEAD_SIMPLE"):
        assert must in keys
    assert len(keys) == 9
