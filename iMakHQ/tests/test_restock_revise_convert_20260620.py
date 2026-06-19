# -*- coding: utf-8 -*-
"""RESTOCK Add→Revise 変換(add_rows_to_revise)の回帰テスト (2026-06-20)。

変換は post-chain(excluder/title-fix/dedup)後の最終CSVに対して control_panel が実施する
(順序保証)。ここでは変換ルール本体(純関数)を固定: Action→Revise / ItemID挿入 / qty=1 /
PicURL・ScheduleTime 列削除 / itemID引けない行は skip(fail-closed)。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

import psa_restock_revise_csv as rv

_CERT = "CDA:Certification Number - (ID: 27503)"


def _header():
    return ["*Action(SiteID=US|Country=JP)", _CERT, "*Quantity", "PicURL", "ScheduleTime", "*Title"]


def test_add_to_revise_basic():
    header = _header()
    rows = [
        ["Add", "111", "1", "http://pic/1.jpg", "2026-07-01", "Card A"],
        ["Add", "222", "1", "http://pic/2.jpg", "2026-07-01", "Card B"],
    ]
    c2i = {"111": "9001", "222": "9002"}
    rh, rr, skipped = rv.add_rows_to_revise(header, rows, c2i)
    # Action→Revise, ItemID が Action 直後に挿入
    assert rh[0].startswith("*Action")
    assert rh[1] == "ItemID"
    # PicURL / ScheduleTime 列は除去
    assert "PicURL" not in rh and "ScheduleTime" not in rh
    assert skipped == []
    # 1行目: Action=Revise, ItemID=9001, qty=1
    assert rr[0][0] == "Revise"
    assert rr[0][1] == "9001"
    qi = rh.index("*Quantity")
    assert rr[0][qi] == "1"


def test_no_itemid_is_skipped_failclosed():
    """cert→itemID が引けない行は Revise できない → 出力せず skipped(誤Revise防止)。"""
    header = _header()
    rows = [["Add", "999", "1", "p", "t", "Card X"]]
    rh, rr, skipped = rv.add_rows_to_revise(header, rows, {})   # マップ空
    assert rr == []
    assert len(skipped) == 1 and skipped[0][0] == "999"
