# -*- coding: utf-8 -*-
"""PSA再仕入れ② の残数を二重に引かない (2026-09-10 ユーザー指摘).

> PSA再仕入れ③やったら、②がまた1になったけど

「上げられないと分かっている行」を残数から外した後、さらに「今日もう出した行」を
引く時に **同じ札をもう一度** 引いていた。実測: 押せば2件出るのに 1件と表示。

実例 (2026-09-10): 生成できる cert 3件のうち
  146711355 (カビゴン) … 入稿前に落とした = 上げられない → 外す
  146280449 / 143972967 … まだCSVにしていない = 押せば出る
1件目が「上げられない」でも「今日生成済」でも引かれ、2 → 1 になっていた。
"""
import os
import sys

TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
sys.path.insert(0, TOOLS)

import psa_restock_build as RB          # noqa: E402


def _rows(*iids):
    """RESTOCK確定 タブ相当の行 (未入稿=pending)。"""
    head = ["itemID", "card_no", "title", "最安チャネル", "最安¥", "eBay現$",
            "V8判定", "確認済仕入URL", "ebay_url", "確証日", "RESTOCK状態", "状態確認日"]
    return [head] + [[i, "X-1", "t", "snkrdunk", "1000", "10.0", "", "", "", "2026-09-01",
                      "入稿待ち(qty=0)", "2026-09-10"] for i in iids]


def _patch(monkeypatch, built=(), undeliverable=()):
    monkeypatch.setattr(RB, "built_today", lambda: set(built))
    monkeypatch.setattr(RB, "undeliverable", lambda: set(undeliverable))
    monkeypatch.setattr(RB, "build_restock_input",
                        lambda pending, c2, km: ({"certs": [c2[(p.get("itemID") or "").strip()]
                                                            for p in pending
                                                            if c2.get((p.get("itemID") or "").strip())],
                                                  "forced": []}, []))


def test_blocked_row_is_subtracted_only_once(monkeypatch):
    """上げられない札は1回だけ引く (今日生成済でも二重に引かない)。"""
    _patch(monkeypatch, built=["A"], undeliverable=["A"])
    got = RB.count_workload(rows=_rows("A", "B", "C"),
                            itemid_to_cert={"A": "c1", "B": "c2", "C": "c3"})
    assert got["actionable"] == 2, got
    assert got["blocked"] == 1


def test_built_today_still_reduces_a_live_row(monkeypatch):
    """まだ上げられる札を今日出していれば、そのぶんは減る。"""
    _patch(monkeypatch, built=["B"], undeliverable=[])
    got = RB.count_workload(rows=_rows("A", "B"),
                            itemid_to_cert={"A": "c1", "B": "c2"})
    assert got["actionable"] == 1 and got["built_today"] == 1, got


def test_nothing_left_is_zero(monkeypatch):
    _patch(monkeypatch, built=["A", "B"], undeliverable=[])
    got = RB.count_workload(rows=_rows("A", "B"),
                            itemid_to_cert={"A": "c1", "B": "c2"})
    assert got["actionable"] == 0, got
