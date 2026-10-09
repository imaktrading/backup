# -*- coding: utf-8 -*-
"""ミラーの行が無くて落ちた cert は、依頼書ではなくカタログの入力 mirror_variant_input.json に書く (2026-10-09 B-024)。"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
import build_fail_watch as B

WHY = "刷りがPSAラベルと合わない — SV2a-079 — PSA は MASTER BALL REVERSE HOLO だが行は 通常 / 合う行が0件で決められない"


def test_mirror_requests():
    got = B.mirror_requests({"158627035": WHY, "1": "セルフチェック失敗 …"})
    assert got == {"158627035": {"base": "SV2a-079", "psa": "MASTER BALL REVERSE HOLO"}}


def test_write_input_once(tmp_path):
    p = str(tmp_path / "in.json")
    r = {"158627035": {"base": "SV2a-079", "psa": "MASTER BALL REVERSE HOLO"}}
    assert B.write_mirror_input(r, "2026-10-09T20:00:00", path=p) == 1
    assert B.write_mirror_input(r, "2026-10-09T21:00:00", path=p) == 0          # 同じ中身は足し直さない
    d = json.load(open(p, encoding="utf-8"))
    assert d["158627035"]["at"] == "2026-10-09T20:00:00"


def test_run_logs_mirror_line(tmp_path):
    lines = []
    log = "  → #158627035 ヤドン ✓\n    ⏭️ Skip (刷りがPSAラベルと合わない): #158627035 SV2a-079 — PSA は MASTER BALL REVERSE HOLO だが行は 通常 / 合う行が0件で決められない\n"
    B.run(log, lines.append, ledger_path=str(tmp_path / "l.json"), verified_path=str(tmp_path / "v.json"),
          add_backlog=lambda c, r: 0, mirror_path=str(tmp_path / "m.json"))
    assert any(l.startswith("🪞 ミラーの行の作成を頼んだ: 1件") for l in lines)
