# -*- coding: utf-8 -*-
"""毎朝のデータの見張り: 1ビット化けだけを拾い、普通の書き換えは拾わない (2026-09-29)。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import data_integrity_watch as W  # noqa: E402

COLS = ["category", "product_id", "images"]


def test_single_bit_flip_is_found():
    old = {1: (b"pokemon", b"MC-409", b"large/MC/049125_P")}
    new = {1: (b"pokemon", b"MC-409", b"large/MC/849125_P")}       # '0'(0x30) → '8'(0x38) = 1ビット
    got = W.bitflips(old, new, COLS)
    assert len(got) == 1 and got[0]["column"] == "images" and got[0]["bits"] == ["0x8"]


def test_normal_edits_are_not_flips():
    old = {1: (b"a", b"X", b"Pokemon"), 2: (b"a", b"Y", b"abc")}
    new = {1: (b"a", b"X", b"pokemon"),                               # 大文字小文字 (0x20) = 人の直し
           2: (b"a", b"Y", b"abcdef"),                                # 長さが違う = 普通の書き換え
           3: (b"a", b"Z", b"new")}                                   # 新しい行
    assert W.bitflips(old, new, COLS) == []


def test_backup_calls_the_watch():
    src = open(os.path.join(os.path.dirname(W.__file__), "data_backup.py"), encoding="utf-8").read()
    assert "data_integrity_watch.run()" in src


def test_direction_repaired_value_is_not_reported():
    """2026-09-30: 「前」が化けていて「今」が直った値だった10欄に「前に戻せ」と出した。前のどれかに今の値があれば外す。"""
    cols = ["category", "product_id", "language"]
    older = {1: (b"p", b"A", b"ja")}                                  # 化ける前
    old = {1: (b"p", b"A", b"na")}                                    # 化けたまま2日残った
    new = {1: (b"p", b"A", b"ja")}                                    # 直った
    fl = W.bitflips(old, new, cols)
    assert len(fl) == 1
    assert W.classify(fl, old, new, [old, older], cols) == []


def test_direction_new_flip_and_unknown():
    cols = ["category", "product_id", "language"]
    old = {1: (b"p", b"A", b"ja"), 2: (b"p", b"B", b"ja")}
    new = {1: (b"p", b"A", b"na"), 2: (b"p", b"B", b"na")}
    ref = {1: (b"p", b"A", b"ja")}                                    # 2 は2つ前に無い
    got = W.classify(W.bitflips(old, new, cols), old, new, [ref], cols)
    assert {f["rowid"]: f["broken"] for f in got} == {1: "now", 2: "unknown"}


def test_second_request_same_day_when_content_differs(tmp_path, monkeypatch):
    """2026-09-30: 朝の1通を閉じた後に骨組みが壊れたが、同じ日の名前が在るので依頼が出なかった。"""
    monkeypatch.setattr(W, "REQ_DIR", str(tmp_path))
    a = {"quick_check": "ok", "flips": [{"rowid": 1, "column": "x", "offsets": [0], "was": "a", "now": "b",
                                         "broken": "now"}], "pair": ["p", "q"], "refs": []}
    p1 = W._write_request(a)
    os.rename(p1, p1.replace(".md", "_processed.md"))
    assert W._write_request(a) == ""                                  # 同じ中身は2通目を出さない
    b = {"quick_check": "*** broken", "flips": [], "pair": ["p", "q"], "refs": []}
    p2 = W._write_request(b)
    assert p2.endswith("_auto_2.md")
    assert W._write_request(b) == ""


def test_hourly_logs_marks_and_requests_when_broken(tmp_path, monkeypatch):
    """2026-09-30: いつ壊れたかを1時間の幅に絞る。壊れていたら依頼書、毎回 変更カウンタ等を1行残す。"""
    import json
    db = tmp_path / "p.sqlite"
    db.write_bytes(b"\0" * 24 + (19).to_bytes(4, "big") + b"\0" * 72)
    monkeypatch.setattr(W, "DB", str(db))
    monkeypatch.setattr(W, "HOURLY_LOG", str(tmp_path / "h.jsonl"))
    monkeypatch.setattr(W, "REQ_DIR", str(tmp_path))
    monkeypatch.setattr(W, "quick_check", lambda path=None: "*** broken")
    st = W.run_hourly()
    assert st["change_counter"] == 19 and st["request"].endswith("_auto.md")
    assert json.loads((tmp_path / "h.jsonl").read_text(encoding="utf-8"))["quick_check"] == "*** broken"
