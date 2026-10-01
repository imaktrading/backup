# -*- coding: utf-8 -*-
"""検収の「公式との突合」は KAGOYA の結果を読む — 古い / 無い / 読めないは赤.

依頼: `requests/2026-10-01_claim_check_read_kagoya_drift.md` [IMPLEMENT-GO]

2026-10-01 までは検収が**自分でもう一度公式を読んでいた**ので、突合が1日2回走っていた。
★黙って緑にしないことが肝なので、赤になる3つの道をここで固定する。
"""
import importlib.util
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _mod():
    for p in (str(ROOT), str(ROOT / "tools")):
        if p not in sys.path:
            sys.path.insert(0, p)
    spec = importlib.util.spec_from_file_location("_cc", ROOT / "tools" / "claim_check.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _write(d: Path, job: str, at: datetime, body: str) -> None:
    (d / (job + ".out")).write_text(body, encoding="utf-8")
    (d / (job + ".done.json")).write_text(json.dumps(
        {"job": job, "rc": 0, "at": at.isoformat(timespec="seconds")}), encoding="utf-8")


def _run(m, tmp: Path):
    m._KAGOYA_OUT = tmp
    return m.check_official_drift(False)


def test_all_fresh_and_zero_is_green(tmp_path):
    m = _mod()
    now = datetime.now()
    for job in m._DRIFT_JOBS:
        _write(tmp_path, job, now, "突合 100枚 / 差分 0件")
    ok, detail = _run(m, tmp_path)
    assert ok, detail


def test_missing_result_is_red(tmp_path):
    m = _mod()
    now = datetime.now()
    for job in m._DRIFT_JOBS[1:]:            # 1本だけ置かない
        _write(tmp_path, job, now, "突合 100枚 / 差分 0件")
    ok, detail = _run(m, tmp_path)
    assert not ok and "結果が無い" in detail, detail


def test_stale_result_is_red(tmp_path):
    m = _mod()
    now = datetime.now()
    old = now - timedelta(days=m._DRIFT_MAX_AGE_DAYS + 1)
    for job in m._DRIFT_JOBS:
        _write(tmp_path, job, now, "突合 100枚 / 差分 0件")
    _write(tmp_path, m._DRIFT_JOBS[0], old, "突合 100枚 / 差分 0件")
    ok, detail = _run(m, tmp_path)
    assert not ok and "日前" in detail, detail


def test_unreadable_result_is_red(tmp_path):
    m = _mod()
    now = datetime.now()
    for job in m._DRIFT_JOBS:
        _write(tmp_path, job, now, "突合 100枚 / 差分 0件")
    (tmp_path / (m._DRIFT_JOBS[0] + ".done.json")).write_text("{壊れている", encoding="utf-8")
    ok, detail = _run(m, tmp_path)
    assert not ok and "読めない" in detail, detail


def test_drift_found_is_red(tmp_path):
    m = _mod()
    now = datetime.now()
    for job in m._DRIFT_JOBS:
        _write(tmp_path, job, now, "突合 100枚 / 差分 0件")
    _write(tmp_path, "drift_pokemon", now, "**欠落 5枚 / 差分が残っている弾 2**")
    ok, detail = _run(m, tmp_path)
    assert not ok and "差分 5" in detail, detail


def test_does_not_fetch_official_itself(tmp_path, monkeypatch):
    """★公式を読み直さないこと (読んでいたら1日2回になる)."""
    m = _mod()
    called = []
    monkeypatch.setattr(m.subprocess, "run",
                        lambda *a, **k: called.append(a) or (_ for _ in ()).throw(
                            AssertionError("公式を読み直している")))
    now = datetime.now()
    for job in m._DRIFT_JOBS:
        _write(tmp_path, job, now, "突合 100枚 / 差分 0件")
    ok, _ = _run(m, tmp_path)
    assert ok and not called
