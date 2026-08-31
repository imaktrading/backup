# -*- coding: utf-8 -*-
"""`--result-json` に別名を渡すと itemID の書き戻しが黙って空振りする (2026-08-27)。

何が起きるか:
    出品直後の書き戻し (`itemid_writeback_audit._load_just_listed`) が読むのは
    **固定名 `last_upload_result.json`** だけ。`ebay_upload_csv.py --result-json` に
    別名を渡すと、そこにしか書かないので書き戻しが**何も見つけられずに終わる**
    (エラーも出ない = silent)。2026-08-27 の再出し3件がこれに当たり、
    後から `--apply --no-cache` で拾い直した。

守ること: 指定先に書くのに加えて、**CSV と同じ場所の既定名にも必ず書く**。
同じ場所を指しているなら1回だけ書く (二重書き込みしない)。

依頼書: hq/requests/2026-08-27_writeback_undoes_cull_takedown.md (「ついでに」節)
"""
from __future__ import annotations

import os
import sys

HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HQ, "tools"))

import ebay_upload_csv as U                                     # noqa: E402

CSV_DIR = os.path.join(HQ, "csv_output")
CSV = os.path.join(CSV_DIR, "tcg_upload_20260827_191122.csv")
DEFAULT = os.path.join(CSV_DIR, "last_upload_result.json")


def _norm(paths):
    return [os.path.normcase(os.path.abspath(p)) for p in paths]


class TestResultPaths:
    def test_別名を渡しても既定名にも書く(self):
        other = os.path.join(CSV_DIR, "tcg_redo_result.json")
        got = _norm(U.result_paths(other, CSV))
        assert _norm([DEFAULT])[0] in got, "既定名に書かないと書き戻しが空振りする"
        assert _norm([other])[0] in got, "指定先にも従来どおり書く"

    def test_既定名を渡したら二重に書かない(self):
        assert len(U.result_paths(DEFAULT, CSV)) == 1

    def test_指定なしでも既定名に書く(self):
        assert _norm(U.result_paths("", CSV)) == _norm([DEFAULT])

    def test_既定名は_CSV_と同じ場所(self):
        """書き戻しは result json と同じ場所から CSV を開く (csv は basename 保存)。"""
        for p in U.result_paths("", CSV):
            assert os.path.dirname(os.path.abspath(p)) == os.path.abspath(CSV_DIR)

    def test_CSV_が無ければ指定先だけ(self):
        assert U.result_paths("x.json", "") == ["x.json"]
        assert U.result_paths("", "") == []


class TestWriteResultIsCalledForEachPath:
    """main が result_paths を回して書いていること (1つだけ書いて終わらない)。"""

    def test_main_は_result_paths_を回している(self):
        src = open(os.path.join(HQ, "tools", "ebay_upload_csv.py"),
                   encoding="utf-8").read()
        assert "for _p in result_paths(a.result_json, a.csv):" in src
        assert "if write_result(a.result_json, build_result(" not in src
