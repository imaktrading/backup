"""台帳の排他 (HIGH/LOW 並走の前提条件) — 2026-08-19.

守る性質:
    取下げ待ち (pending_revise) 等の台帳は「全行読む → 消す分を外す → 全部書き直す」
    更新をしている。HIGH と LOW を並走させると、書き直しの最中に相手が append した行が
    まるごと消える。消えたのが取下げ待ちなら、売切れた商品が eBay に残り続ける
    (= 履行不能 → キャンセル → Defect Rate)。しかも silent。

    そこで remove_entries は「自分が読んだ内容を書き戻す」のではなく
    「lock を取ってから読み直し、消すと決めた entry だけ落とす」。
"""
from __future__ import annotations

import json
import socket
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import ledger_lock  # noqa: E402
from ledger_lock import ledger_lock as lock_cm, remove_entries, LedgerBusy  # noqa: E402


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    """台帳と lock を tmp に隔離する (本番 decision_log を触らない)."""
    monkeypatch.setattr(ledger_lock, "LOCK_PATH", tmp_path / ".ledger.lock")
    return tmp_path / "pending.jsonl"


def _write(path, entries):
    path.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries),
                    encoding="utf-8")


def _read(path):
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def test_removes_only_matching_and_archives(ledger, tmp_path):
    _write(ledger, [{"item_id": "1"}, {"item_id": "2"}, {"item_id": "3"}])
    archive = tmp_path / "processed.jsonl"

    n = remove_entries(ledger, lambda e: e["item_id"] in {"1", "3"},
                       archive_path=archive, stamp_field="consumed_at")

    assert n == 2
    assert [e["item_id"] for e in _read(ledger)] == ["2"]
    archived = _read(archive)
    assert {e["item_id"] for e in archived} == {"1", "3"}
    assert all(e["consumed_at"] for e in archived)   # 証跡の時刻が押される


def test_entry_appended_after_decision_survives(ledger):
    """★ 本丸: 消す対象を決めた後に届いた行を巻き込まないこと.

    実運用では「eBay に qty を問い合わせる」間 (数十秒) に、並走 cycle が
    新しい売切れを append する。その行が消えると取下げ漏れになる。
    """
    _write(ledger, [{"item_id": "1"}, {"item_id": "2"}])
    doomed = {"1"}                              # ← 遅い API 判定の結果 (lock の外で決まる)

    # 判定と書換えの「間」に別 cycle が append した状況を作る
    with open(ledger, "a", encoding="utf-8") as f:
        f.write(json.dumps({"item_id": "99"}) + "\n")

    remove_entries(ledger, lambda e: e["item_id"] in doomed)

    assert [e["item_id"] for e in _read(ledger)] == ["2", "99"]


def test_broken_line_is_kept(ledger):
    """壊れた行は消さない (debug 可能にする / 巻き添えで消さない)."""
    ledger.write_text('{"item_id": "1"}\nTHIS IS NOT JSON\n', encoding="utf-8")

    remove_entries(ledger, lambda e: True)

    assert ledger.read_text(encoding="utf-8").strip() == "THIS IS NOT JSON"


def test_missing_ledger_is_noop(ledger):
    assert remove_entries(ledger, lambda e: True) == 0


def test_busy_lock_raises_instead_of_writing(ledger, tmp_path):
    """lock を取れなければ書き換えない (= 台帳は残る = 安全側)."""
    ledger_lock.LOCK_PATH.write_text(
        f"pid={_alive_pid()} host={socket.gethostname()} ts=now\n", encoding="utf-8")
    _write(ledger, [{"item_id": "1"}])

    with pytest.raises(LedgerBusy):
        remove_entries(ledger, lambda e: True, timeout_sec=1)

    assert [e["item_id"] for e in _read(ledger)] == ["1"]   # 消えていない


def test_stale_lock_of_dead_process_is_stolen(ledger, monkeypatch):
    """持ち主が死んでいる lock で永久に詰まらない (PC 再起動/クラッシュ後の復帰)."""
    monkeypatch.setattr(ledger_lock, "STALE_SEC", 0)
    monkeypatch.setattr(ledger_lock, "_pid_alive", lambda pid: False)
    ledger_lock.LOCK_PATH.write_text(
        f"pid=999999 host={socket.gethostname()} ts=now\n", encoding="utf-8")
    _write(ledger, [{"item_id": "1"}])

    assert remove_entries(ledger, lambda e: True) == 1


def test_two_processes_do_not_lose_appends(ledger, tmp_path):
    """★ 実プロセス 2 本で同時に append しても 1 行も落ちないこと."""
    script = tmp_path / "appender.py"
    script.write_text(
        "import json, sys\n"
        f"sys.path.insert(0, r'{ROOT}')\n"
        "import ledger_lock\n"
        "from pathlib import Path\n"
        f"ledger_lock.LOCK_PATH = Path(r'{ledger_lock.LOCK_PATH}')\n"
        f"led = Path(r'{ledger}')\n"
        "tag = sys.argv[1]\n"
        "for i in range(60):\n"
        "    with ledger_lock.ledger_lock():\n"
        "        with open(led, 'a', encoding='utf-8') as f:\n"
        "            f.write(json.dumps({'item_id': f'{tag}-{i}'}) + '\\n')\n",
        encoding="utf-8",
    )
    ledger.write_text("", encoding="utf-8")

    procs = [subprocess.Popen([sys.executable, str(script), tag]) for tag in ("A", "B")]
    for p in procs:
        assert p.wait(timeout=180) == 0

    ids = [e["item_id"] for e in _read(ledger)]
    assert len(ids) == 120, f"append が落ちた: {len(ids)}/120"
    assert len(set(ids)) == 120


def _alive_pid() -> int:
    """確実に生きている pid (= 自分自身)."""
    import os
    return os.getpid()
