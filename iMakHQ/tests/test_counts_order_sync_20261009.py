# -*- coding: utf-8 -*-
"""残件の数え直しで注文の取り込みも回す (2026-10-09 ユーザー)。"""
import json
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "console"))
import counts as C


class _R:
    def __init__(self, rc):
        self.returncode, self.stdout, self.stderr = rc, "", "boom"


def test_order_sync_runs_with_write_and_reads_status(monkeypatch, tmp_path):
    p = tmp_path / "st.json"
    p.write_text(json.dumps({"waiting": 3, "at": "2026-10-09T07:00:00"}), encoding="utf-8")
    seen = []
    monkeypatch.setattr(C, "ORDER_STATUS", str(p))
    monkeypatch.setattr(subprocess, "run", lambda cmd, **k: seen.append(cmd) or _R(0))
    assert C.order_sync()["waiting"] == 3
    assert seen[0][-2:] == [os.path.join(C.TOOLS, "order_purchase_sync.py"), "--write"]


def test_order_sync_failure_is_an_error(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda cmd, **k: _R(1))
    with pytest.raises(RuntimeError):
        C.order_sync()


def test_recount_includes_order():
    src = open(C.__file__, encoding="utf-8").read()
    assert '"order": order_sync' in src
