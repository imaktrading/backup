"""opcg_dump_refresh の安全弁テスト (2026-08-02).

守りたいこと:
  - 取得が失敗した / dump が減った / invariant が動いた → **巻き戻して exit 1**
  - 何も壊れていない時だけ 0 を返す (「正常」を軽々しく出さない)
  - 取得が止まっていたら --check が気づく (2ヶ月止まっても誰も気づかなかった件の再発防止)
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import opcg_dump_refresh as odr  # noqa: E402


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """DUMPS / DB / LOG_DIR を tmp に逃がす (実データを一切触らない)."""
    dumps = tmp_path / "_opcg_official_dumps"
    dumps.mkdir()
    for i in range(60):
        (dumps / f"series_{i}.json").write_text("{}", encoding="utf-8")
    db = tmp_path / "products.sqlite"
    db.write_bytes(b"not-a-real-db")
    monkeypatch.setattr(odr, "DATA", tmp_path)
    monkeypatch.setattr(odr, "DUMPS", dumps)
    monkeypatch.setattr(odr, "DB", db)
    monkeypatch.setattr(odr, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(odr, "FETCH", tmp_path / "fetch.py")
    (tmp_path / "fetch.py").write_text("", encoding="utf-8")
    return tmp_path


def _fetch_result(monkeypatch, rc=0, after=None, dumps=None):
    """subprocess.run を差し替え、取得の副作用 (dump 数の変化) を模す."""
    def fake_run(cmd, **kw):
        if after is not None and dumps is not None:
            for f in dumps.glob("*.json"):
                f.unlink()
            for i in range(after):
                (dumps / f"series_{i}.json").write_text("{}", encoding="utf-8")

        class R:
            returncode = rc
            stdout = "ok"
            stderr = ""
        return R()
    monkeypatch.setattr(odr.subprocess, "run", fake_run)


class TestInvariants:
    def test_expected_counts_are_pinned(self):
        """人が焼いた3つの tag 件数は勝手に変えない (変えるなら根拠つきで)."""
        assert odr.INVARIANTS == {
            "blanked_by_ultra_prism_mismap_20260731": 327,
            "filter_map_backfill_20260801": 21,
            "filter_map_restamp_20260801": 76,
        }

    def test_min_dumps_below_official_series_count(self):
        """公式 series 61 に対し、下限は少し低め (未発売分の増減を許容する)."""
        assert 0 < odr.MIN_DUMPS <= 61


class TestRefreshGuards:
    def test_ok_when_nothing_broke(self, sandbox, monkeypatch):
        _fetch_result(monkeypatch, rc=0)
        monkeypatch.setattr(odr, "invariant_counts", lambda: dict(odr.INVARIANTS))
        assert odr.refresh() == 0

    def test_fails_and_restores_when_fetch_errors(self, sandbox, monkeypatch):
        _fetch_result(monkeypatch, rc=1)
        monkeypatch.setattr(odr, "invariant_counts", lambda: dict(odr.INVARIANTS))
        assert odr.refresh() == 1
        assert odr.dump_count() == 60, "巻き戻して元の dump 数に戻ること"

    def test_fails_when_dumps_shrink(self, sandbox, monkeypatch):
        """公式が落ちていて空 dump で上書きした、を弾く."""
        _fetch_result(monkeypatch, rc=0, after=3, dumps=odr.DUMPS)
        monkeypatch.setattr(odr, "invariant_counts", lambda: dict(odr.INVARIANTS))
        assert odr.refresh() == 1
        assert odr.dump_count() == 60, "巻き戻して元の dump 数に戻ること"

    def test_fails_when_invariant_moves(self, sandbox, monkeypatch):
        """取り込みが過去の人手修正を巻き戻した、を弾く."""
        _fetch_result(monkeypatch, rc=0)
        broken = dict(odr.INVARIANTS)
        broken["filter_map_restamp_20260801"] = 0
        monkeypatch.setattr(odr, "invariant_counts", lambda: broken)
        assert odr.refresh() == 1

    def test_does_not_fetch_when_script_missing(self, sandbox, monkeypatch):
        odr.FETCH.unlink()
        called = []
        monkeypatch.setattr(odr.subprocess, "run", lambda *a, **k: called.append(1))
        assert odr.refresh() == 1
        assert not called, "取得スクリプトが無い時は起動しない"

    def test_does_not_fetch_when_backup_fails(self, sandbox, monkeypatch):
        called = []
        monkeypatch.setattr(odr.subprocess, "run", lambda *a, **k: called.append(1))
        monkeypatch.setattr(odr.shutil, "copytree", lambda *a, **k: (_ for _ in ()).throw(OSError("no space")))
        assert odr.refresh() == 1
        assert not called, "退避できないなら取得しない (戻せない状態を作らない)"


class TestCheck:
    def test_reports_stale(self, sandbox, monkeypatch):
        monkeypatch.setattr(odr, "dump_age_days", lambda: odr.STALE_DAYS + 1)
        monkeypatch.setattr(odr, "invariant_counts", lambda: dict(odr.INVARIANTS))
        assert odr.check() == 1

    def test_ok_when_fresh(self, sandbox, monkeypatch):
        monkeypatch.setattr(odr, "dump_age_days", lambda: 1.0)
        monkeypatch.setattr(odr, "invariant_counts", lambda: dict(odr.INVARIANTS))
        assert odr.check() == 0

    def test_reports_when_no_dumps_at_all(self, sandbox, monkeypatch):
        for f in odr.DUMPS.glob("*.json"):
            f.unlink()
        monkeypatch.setattr(odr, "invariant_counts", lambda: dict(odr.INVARIANTS))
        assert odr.check() == 1
