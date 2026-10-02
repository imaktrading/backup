"""data_integrity_watch: UNIQLO の評価・在庫の変化を1ビット化けと数えない (2026-10-02 カタログ回答)。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import data_integrity_watch as W  # noqa: E402


def test_rating_change_is_not_a_flip():
    cols = ["product_id", "specs"]
    old = {1: (b"E486450-000", b'{"rating": 0, "color": "BLACK"}')}
    new = {1: (b"E486450-000", b'{"rating": 4, "color": "BLACK"}')}     # '0'^'4' = 1ビット
    assert W.bitflips(old, new, cols) == []


def test_other_key_flip_still_found():
    cols = ["product_id", "specs"]
    old = {1: (b"X", b'{"rating": 4, "color": "BLACK"}')}
    new = {1: (b"X", b'{"rating": 4, "color": "BLACC"}')}               # 'K'^'C' = 0x08
    assert len(W.bitflips(old, new, cols)) == 1


def test_only_volatile_changed():
    assert W.only_volatile_changed(b'{"rating": 4.5, "stock_by_size": {"S": 1}}',
                                   b'{"rating": 4.4, "stock_by_size": {"S": 0}}') is True
    assert W.only_volatile_changed(b'{"rating": 4, "name": "a"}', b'{"rating": 4, "name": "c"}') is False
    assert W.only_volatile_changed(b'{"rating": 4', b'{"rating": 5') is False   # 壊れた JSON は数える
