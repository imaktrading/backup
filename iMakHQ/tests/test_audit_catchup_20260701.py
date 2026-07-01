# -*- coding: utf-8 -*-
"""audit_catchup: SessionStart キャッチアップの監査ログ判定 + marker round-trip (2026-07-01)。
価格抵抗など非監査ログを除外し、監査/生成ログのみ拾うことを検証。"""
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "tools")))
import audit_catchup as m


def test_audit_log_detected():
    assert m.is_audit_log("=== CSV UPシグナル (2026-07-01) ===\n...")
    assert m.is_audit_log("監査サマリー ...")
    assert m.is_audit_log("120件を処理しました")
    assert m.is_audit_log("csv_auditor_20260701.md 出力")


def test_non_audit_log_excluded():
    # 価格抵抗ログは監査ではない → 除外
    assert not m.is_audit_log("=== 💲 価格抵抗 (2026-07-01) ===\ncmd: python price_resistance.py\n")
    assert not m.is_audit_log("")


def test_marker_roundtrip(tmp_path, monkeypatch):
    marker = tmp_path / "mk.txt"
    monkeypatch.setattr(m, "MARKER", str(marker))
    assert m._last_ts() == 0.0            # 無ければ0
    m._save_ts(1234.5)
    assert m._last_ts() == 1234.5
