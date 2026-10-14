# -*- coding: utf-8 -*-
"""数え直しの中で同じ JSON を読み直さない json_memo (2026-10-14 ユーザー「数えなおし、もっと早くできない？」)。

補URL の数えが 6分13秒 → 47秒 (同じファイルを 5,697回 読み直していた)。結果は使い回し無しと一致を確認済み。
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

import json_memo  # noqa: E402


def test_reads_once_inside_count(tmp_path, monkeypatch):
    monkeypatch.setenv("SHEET_READ_MEMO", "1")
    p = tmp_path / "v.json"
    p.write_text(json.dumps({"a": 1}), encoding="utf-8")
    a = json_memo.load(str(p))
    assert a == {"a": 1}
    assert json_memo.load(str(p)) is a          # 2回目は同じ物 (id での使い回しが効く)


def test_rereads_when_file_changes(tmp_path, monkeypatch):
    monkeypatch.setenv("SHEET_READ_MEMO", "1")
    p = tmp_path / "v.json"
    p.write_text(json.dumps({"a": 1}), encoding="utf-8")
    json_memo.load(str(p))
    p.write_text(json.dumps({"a": 2, "b": 3}), encoding="utf-8")
    assert json_memo.load(str(p)) == {"a": 2, "b": 3}


def test_off_outside_count(tmp_path, monkeypatch):
    monkeypatch.delenv("SHEET_READ_MEMO", raising=False)
    p = tmp_path / "v.json"
    p.write_text(json.dumps({"a": 1}), encoding="utf-8")
    assert json_memo.load(str(p)) is not json_memo.load(str(p))


def test_missing_or_broken_file_is_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("SHEET_READ_MEMO", "1")
    assert json_memo.load(str(tmp_path / "none.json")) == {}
    bad = tmp_path / "bad.json"
    bad.write_text("{", encoding="utf-8")
    assert json_memo.load(str(bad)) == {}


def test_on_with_json_read_memo(tmp_path, monkeypatch):
    # 補URL ③ / 再仕入れ ① の main が JSON_READ_MEMO=1 を立てる (2026-10-14 補URL ③ 補充 6分5秒→1分22秒)
    monkeypatch.delenv("SHEET_READ_MEMO", raising=False)
    monkeypatch.setenv("JSON_READ_MEMO", "1")
    p = tmp_path / "v.json"
    p.write_text(json.dumps({"a": 1}), encoding="utf-8")
    assert json_memo.load(str(p)) is json_memo.load(str(p))


def test_mains_turn_memo_on():
    here = os.path.join(os.path.dirname(__file__), "..", "tools")
    for f in ("psa_hoju_fill.py", "psa_resource_gate.py"):
        s = open(os.path.join(here, f), encoding="utf-8").read()
        assert 'os.environ.setdefault("JSON_READ_MEMO", "1")' in s[s.index("def main("):]
