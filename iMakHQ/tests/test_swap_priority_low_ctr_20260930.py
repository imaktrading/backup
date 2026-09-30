# -*- coding: utf-8 -*-
"""入れ替え (補4〜5本) は「表示が多いのにクリックされない」出品から先に回す (2026-09-30 ユーザー確定)。

トラフィックレポート 9/30: 表示3,000回以上で閲覧2回以下が45件。値段は仕入値から決まるので、
安い仕入元に替えれば値段が下がる。補充 (補0〜3本) の並び (少ない順) は変えない。
"""
import json
import os
import sys

TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
sys.path.insert(0, TOOLS)

import psa_hoju_fill as H  # noqa: E402


def test_priority_first_keeps_rest_order():
    ts = [{"itemID": x} for x in ("a", "b", "c", "d")]
    got = [t["itemID"] for t in H.put_priority_first(ts, ["d", "zz", "b"])]
    assert got == ["d", "b", "a", "c"]


def test_missing_file_means_no_change(tmp_path):
    assert H.load_swap_priority(str(tmp_path / "none.json")) == []
    ts = [{"itemID": "a"}, {"itemID": "b"}]
    assert H.put_priority_first(ts, []) == ts


def test_load_reads_iids(tmp_path):
    p = tmp_path / "p.json"
    p.write_text(json.dumps({"iids": ["1", " 2 ", ""]}), encoding="utf-8")
    assert H.load_swap_priority(str(p)) == ["1", "2"]


def test_applied_only_to_swap_side():
    src = open(os.path.join(TOOLS, "psa_hoju_fill.py"), encoding="utf-8").read()
    assert "if min_backups >= CONFIRM_MAX_BACKUPS:" in src
    assert "_swap_t = put_priority_first(rotate_by_last_shown(_swap_t" in src
