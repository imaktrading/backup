"""要対処件数アラートの比較基準 (2026-08-08 誤報事故の再発防止).

事故: 実際の推移は 03:00=277 / 11:00=278 / 17:03=281 (+4/14h) と横ばいだったのに、
16:34 の `--listing` 1件だけの dry-run が state=0 を書き、直後の全件 dry-run が
「前回 0 → 今回 281 (+281)」という**存在しない急増**をメール通報した。

原則: 比較基準は「同じ母数の LIVE 全件実行」同士でしか意味を持たない。
  - dry-run は基準を更新しない
  - 部分実行 (--listing / --supplier) は比較も更新もしない
  - 基準が読めない時は 0 と決めつけない (0 に倒すと必ず誤報になる)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture()
def mm(tmp_path, monkeypatch):
    import main as m
    monkeypatch.setattr(m, "NEEDS_ACTION_STATE", tmp_path / "state.json")
    sent = []
    monkeypatch.setattr(m, "_send_alert_email", lambda subject, body: sent.append((subject, body)) or True)
    monkeypatch.setattr(m, "log", lambda *a, **k: None)
    m._sent = sent
    return m


def _state(m):
    p = m.NEEDS_ACTION_STATE
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def test_live_full_run_updates_baseline_and_alerts_on_increase(mm):
    mm.NEEDS_ACTION_STATE.write_text(json.dumps({"count": 277}), encoding="utf-8")
    mm.alert_if_increased(281, all_updates=[], persist=True, scope="full")
    assert len(mm._sent) == 1 and "+4" in mm._sent[0][0]
    assert _state(mm)["count"] == 281


def test_no_alert_when_not_increased(mm):
    mm.NEEDS_ACTION_STATE.write_text(json.dumps({"count": 281}), encoding="utf-8")
    mm.alert_if_increased(278, persist=True, scope="full")
    assert mm._sent == [] and _state(mm)["count"] == 278


def test_dry_run_never_touches_baseline(mm):
    """★事故の主因1: dry-run が本番の基準を上書きしていた"""
    mm.NEEDS_ACTION_STATE.write_text(json.dumps({"count": 278}), encoding="utf-8")
    mm.alert_if_increased(184, persist=False, scope="full")
    assert _state(mm)["count"] == 278          # 184 で上書きしない
    assert mm._sent == []


def test_partial_run_neither_alerts_nor_persists(mm):
    """★事故の主因2: --listing 1件の実行が state=0 を書き、次の全件実行を +281 と誤報させた"""
    mm.NEEDS_ACTION_STATE.write_text(json.dumps({"count": 278}), encoding="utf-8")
    mm.alert_if_increased(0, persist=True, scope="partial")
    assert _state(mm)["count"] == 278
    assert mm._sent == []


def test_missing_baseline_initializes_without_alert(mm):
    """基準が無い時に 0 と決めつけない (= 初回や state 消失で全件を誤報しない)"""
    mm.alert_if_increased(281, persist=True, scope="full")
    assert mm._sent == []
    assert _state(mm)["count"] == 281          # 次回から比較できるよう初期化はする


def test_corrupted_baseline_does_not_alert(mm):
    mm.NEEDS_ACTION_STATE.write_text("{ broken", encoding="utf-8")
    mm.alert_if_increased(281, persist=True, scope="full")
    assert mm._sent == []
    assert _state(mm)["count"] == 281


def test_reproduce_incident_sequence(mm):
    """事故当日の順番を再現し、修正後は誤報が出ないことを示す"""
    mm.alert_if_increased(277, persist=True, scope="full")      # 03:00 LIVE 全件 (初期化)
    mm.alert_if_increased(278, persist=True, scope="full")      # 11:00 LIVE 全件 (+1 → alert)
    mm._sent.clear()
    mm.alert_if_increased(184, persist=False, scope="full")     # 16:31 dry-run 全件 (uniqlo のみ)
    mm.alert_if_increased(0, persist=False, scope="partial")    # 16:34 dry-run --listing
    mm.alert_if_increased(281, persist=False, scope="full")     # 17:03 dry-run 全件
    assert _state(mm)["count"] == 278                            # 基準は LIVE のまま
    assert len(mm._sent) == 1 and "+3" in mm._sent[0][0]         # 278→281 の実増加分のみ通報
