# -*- coding: utf-8 -*-
"""cull_end.verify_oos: End 直前の現eBay qty 実機確認が fail-closed であることの回帰テスト
(2026-06-28)。

古い funnel を小分け処理する間に補充された listing を誤取下げしない。
fail-closed = qty>0(在庫復活) も qty取得不能(None/例外) も End しない。

★2026-08-23: 「既に終了済み」も除外するようになり、戻り値が
  (kept, revived, failed) → (kept, revived, ended, failed) に増えた。
  静的な funnel CSV から毎回 同じ上位N件が選ばれて2回目以降 進まなかったため。
"""
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools")))
import cull_end


def _items(*ids):
    return [{"item_id": i, "title": f"item {i}"} for i in ids]


def test_qty_zero_kept():
    picked = _items("1", "2")
    kept, revived, ended, failed = cull_end.verify_oos(picked, lambda i: 0)
    assert [r["item_id"] for r in kept] == ["1", "2"]
    assert not revived and not failed


def test_qty_positive_excluded():
    picked = _items("1", "2", "3")
    fetch = {"1": 0, "2": 5, "3": 0}.get
    kept, revived, ended, failed = cull_end.verify_oos(picked, fetch)
    assert [r["item_id"] for r in kept] == ["1", "3"]
    assert [r["item_id"] for r in revived] == ["2"]
    assert not failed


def test_qty_none_excluded_failclosed():
    picked = _items("1", "2")
    kept, revived, ended, failed = cull_end.verify_oos(picked, lambda i: None)
    assert not kept
    assert [r["item_id"] for r in failed] == ["1", "2"]


def test_fetch_exception_excluded_failclosed():
    def boom(i):
        raise RuntimeError("network down")
    picked = _items("1")
    kept, revived, ended, failed = cull_end.verify_oos(picked, boom)
    assert not kept
    assert [r["item_id"] for r in failed] == ["1"]
