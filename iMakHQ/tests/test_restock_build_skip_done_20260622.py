#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""♻ RESTOCK build は実行済(再出品済)を再生成しない (2026-06-22)。

ユーザー指摘: 出品済で在庫切れ(supply無し)になったものまで毎回再Reviseで qty=1 出し直すのはおかしい。
一度再出品したものは出さない(再出品後の取下げは在庫監視くんが担う)。
対策: _pending_from_confirmed_rows が RESTOCK状態=実行済 を除外し、未出品(入稿待ち/新規)だけ返す。
売れ直し(qty=0)は writeback で「入稿待ち」へ戻るので再度拾われる(取りこぼしなし)。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
from psa_restock_build import _pending_from_confirmed_rows  # noqa: E402

H = ["itemID", "card_no", "title", "最安チャネル", "最安¥", "eBay現$", "V8判定",
     "確認済仕入URL", "ebay_url", "確証日", "RESTOCK状態", "状態確認日", "仕入URL"]


def _row(iid, status, cost="1000", url="http://x"):
    r = [""] * len(H)
    r[H.index("itemID")] = iid
    r[H.index("RESTOCK状態")] = status
    r[H.index("最安¥")] = cost
    r[H.index("仕入URL")] = url
    return r


def test_skips_done():
    rows = [H, _row("111", "実行済(qty復活)"), _row("222", "入稿待ち(qty=0)"), _row("333", "")]
    out, skipped = _pending_from_confirmed_rows(rows)
    iids = [o["itemID"] for o in out]
    assert "111" not in iids, "実行済は除外"
    assert "222" in iids and "333" in iids, "入稿待ち/未設定は生成対象"
    assert skipped == 1


def test_all_done_yields_empty():
    rows = [H, _row("111", "実行済(qty復活)"), _row("222", "実行済(qty復活)")]
    out, skipped = _pending_from_confirmed_rows(rows)
    assert out == [] and skipped == 2


def test_empty():
    assert _pending_from_confirmed_rows([]) == ([], 0)
    assert _pending_from_confirmed_rows([H]) == ([], 0)


def test_carries_cost_and_url():
    rows = [H, _row("222", "入稿待ち(qty=0)", cost="3700", url="http://buy")]
    out, _ = _pending_from_confirmed_rows(rows)
    assert out[0]["cost"] == "3700"
    assert out[0]["supply_url"] == "http://buy"
