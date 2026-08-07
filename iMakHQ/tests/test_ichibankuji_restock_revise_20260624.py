# -*- coding: utf-8 -*-
"""一番くじ RESTOCK内容刷新 Add→Revise 変換の回帰テスト (2026-06-24)。

psa_restock_revise と同型だが、cert# でなく CustomLabel(=mercari SKU)→ itemID で逆引き。
変換ルールを固定: Action→Revise / ItemID挿入 / qty=1 / PicURL・ScheduleTime列削除 /
itemID引けない行は skip(fail-closed)。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

import ichibankuji_restock_revise as rv


def _header():
    return ["*Action(SiteID=US|Country=JP)", "CustomLabel", "*Quantity",
            "PicURL", "ScheduleTime", "*Title", "ShippingProfileName"]


def test_add_to_revise_basic():
    header = _header()
    rows = [
        ["Add", "m111", "1", "http://pic/1.jpg", "2026-07-01", "Kuji A", "60-100"],
        ["Add", "m222", "1", "http://pic/2.jpg", "2026-07-01", "Kuji B", "40-60"],
    ]
    s2i = {"m111": "358000000001", "m222": "358000000002"}
    rh, rr, skipped = rv.add_rows_to_revise(header, rows, s2i)
    # Action→Revise, ItemID が Action 直後に挿入
    assert rh[0].startswith("*Action")
    assert rh[1] == "ItemID"
    # PicURL / ScheduleTime 列は除去
    assert "PicURL" not in rh and "ScheduleTime" not in rh
    # 業務Profile列は残す
    assert "ShippingProfileName" in rh
    assert skipped == []
    # 1行目: Action=Revise, ItemID, qty=1
    assert rr[0][0] == "Revise"
    assert rr[0][1] == "358000000001"
    qi = rh.index("*Quantity")
    assert rr[0][qi] == "1"


def test_no_itemid_is_skipped_failclosed():
    """SKU→itemID が引けない行は Revise できない → 出力せず skipped(誤Revise防止)。"""
    header = _header()
    rows = [["Add", "m999", "1", "p", "t", "Kuji X", "60-100"]]
    rh, rr, skipped = rv.add_rows_to_revise(header, rows, {})   # マップ空
    assert rr == []
    assert len(skipped) == 1 and skipped[0][0] == "m999"


def test_missing_action_or_sku_raises():
    """*Action / CustomLabel 列欠落は format 不一致 → 例外(沈黙誤変換を防ぐ)。"""
    import pytest
    with pytest.raises(ValueError):
        rv.add_rows_to_revise(["*Title", "CustomLabel"], [["x", "m1"]], {"m1": "1"})
    with pytest.raises(ValueError):
        rv.add_rows_to_revise(["*Action(x)", "*Title"], [["Add", "x"]], {})
