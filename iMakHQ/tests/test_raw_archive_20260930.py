# -*- coding: utf-8 -*-
"""カタログの _raw を毎晩少しずつ Google ドライブへ送る (2026-09-30)。

背景: 1.8GB を1本で圧縮中にブルースクリーン。守るもの: 1本の上限・一晩の本数・送り済みは二度送らない・変わった物は送り直す。
"""
import os
import sys
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import raw_archive as R  # noqa: E402


def test_plan_splits_and_caps_per_night():
    now = {f"f{i}": [40, 1] for i in range(10)}
    books, left = R.plan(now, {}, part_bytes=100, parts=2)
    assert books == [["f0", "f1"], ["f2", "f3"]]
    assert left == 6


def test_plan_skips_sent_and_resends_changed():
    now = {"a": [10, 1], "b": [10, 2], "c": [10, 3]}
    sent = {"a": [10, 1, "raw_x_01.zip"], "b": [10, 1, "raw_x_01.zip"]}
    books, left = R.plan(now, sent, part_bytes=100, parts=3)
    assert books == [["b", "c"]]
    assert left == 0


def test_write_book_roundtrip(tmp_path):
    src = tmp_path / "raw"
    (src / "d").mkdir(parents=True)
    (src / "d" / "a.json").write_text("{}")
    (src / "d" / "p.jpg").write_bytes(b"\xff\xd8")
    out = tmp_path / "b.zip"
    R.write_book(str(src), ["d/a.json", "d/p.jpg"], str(out))
    with zipfile.ZipFile(out) as z:
        assert sorted(z.namelist()) == ["d/a.json", "d/p.jpg"]
        assert z.getinfo("d/p.jpg").compress_type == zipfile.ZIP_STORED
