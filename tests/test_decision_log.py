#!/usr/bin/env python3
"""decision_log の挙動検証 (Step 8)"""
from __future__ import annotations
import json
import sys
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT / "iMakeBayAPI") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "iMakeBayAPI"))

import decision_log  # noqa: E402

try:
    import pytest
    _HAS_PYTEST = True
except ImportError:
    _HAS_PYTEST = False


def _with_tmp_log_dir(monkey_path: Path):
    """LOG_DIR を tmp ディレクトリに差替"""
    decision_log.LOG_DIR = monkey_path


def test_log_basic_record(tmp_path):
    _with_tmp_log_dir(tmp_path)
    p = decision_log.log_decision(
        project="iMakTCG",
        sku="TEST-001",
        title="Test Card",
        category="TCG(PSA10)",
        price_usd=99.99,
        shipping_jpy=2000,
        status="OK",
        reason="unit test",
    )
    assert p.exists()
    rec = json.loads(p.read_text(encoding="utf-8").splitlines()[0])
    assert rec["project"] == "iMakTCG"
    assert rec["sku"] == "TEST-001"
    assert rec["status"] == "OK"
    assert rec["price_usd"] == 99.99
    assert rec["category"] == "TCG(PSA10)"
    assert "config_version" in rec
    assert "ts" in rec


def test_log_appends_multiple(tmp_path):
    _with_tmp_log_dir(tmp_path)
    for i in range(3):
        decision_log.log_decision(
            project="iMakG-shock", sku=f"GSHOCK-{i}",
            status="OK", reason=f"entry {i}"
        )
    decisions = decision_log.read_today_decisions()
    assert len(decisions) == 3
    assert [d["sku"] for d in decisions] == ["GSHOCK-0", "GSHOCK-1", "GSHOCK-2"]


def test_log_with_error_captures_traceback(tmp_path):
    _with_tmp_log_dir(tmp_path)
    try:
        raise ValueError("synthetic test error")
    except ValueError as e:
        decision_log.log_decision(
            project="iMakTCG", sku="ERR-001",
            status="ERROR", error=e
        )
    decisions = decision_log.read_today_decisions()
    rec = decisions[-1]
    assert rec["status"] == "ERROR"
    assert rec["error_type"] == "ValueError"
    assert "synthetic test error" in rec["error_msg"]
    assert "traceback" in rec
    assert "ValueError" in rec["traceback"]


def test_log_extra_field(tmp_path):
    _with_tmp_log_dir(tmp_path)
    decision_log.log_decision(
        project="iMakMercari", sku="EXT-001",
        status="HOLD", reason="3AI deliberation",
        extra={"deliberation_rounds": 3, "verdict": "HOLD"}
    )
    rec = decision_log.read_today_decisions()[-1]
    assert rec["extra"]["deliberation_rounds"] == 3
    assert rec["extra"]["verdict"] == "HOLD"


def test_log_csv_batch_all_4_projects(tmp_path):
    """Step 8 拡張: 4プロジェクトの category で log_csv_batch が正常動作"""
    _with_tmp_log_dir(tmp_path)
    cases = [
        ("iMakTCG", "TCG(PSA10)"),
        ("iMakG-shock", "G-SHOCK"),
        ("iMakMercari", "Tシャツ(UT)"),
        ("iMak_ichibankuji", "一番くじ"),
    ]
    for project, category in cases:
        decision_log.log_csv_batch(
            project=project,
            category=category,
            output_path=f"/tmp/{project}_test.csv",
            row_count=10,
        )
    decisions = decision_log.read_today_decisions()
    assert len(decisions) == 4
    for rec, (project, category) in zip(decisions, cases):
        assert rec["project"] == project
        assert rec["category"] == category
        assert rec["extra"]["kind"] == "csv_batch"
        assert rec["extra"]["row_count"] == 10
        assert rec["extra"]["fvf_used"] is not None, f"{project}: FVF not captured"
        assert rec["extra"]["exchange_rate_used"] is not None
        # config_version 刻印
        assert rec["config_version"] != "unknown"
        assert "2026-04-25" in rec["config_version"]


def test_log_csv_batch_unknown_category_handled(tmp_path):
    """未知 category でも log_csv_batch は失敗しない（param_lookup_error 記録）"""
    _with_tmp_log_dir(tmp_path)
    decision_log.log_csv_batch(
        project="iMakTest",
        category="UNKNOWN-CATEGORY-XYZ",
        output_path="/tmp/test.csv",
        row_count=0,
    )
    rec = decision_log.read_today_decisions()[-1]
    assert "param_lookup_error" in rec["extra"]
    assert rec["extra"]["fvf_used"] is None


# Standalone runner
if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    import shutil
    fails = 0
    for name, fn in [
        ("basic record", test_log_basic_record),
        ("appends multiple", test_log_appends_multiple),
        ("error captures traceback", test_log_with_error_captures_traceback),
        ("extra field", test_log_extra_field),
    ]:
        tmp = Path(tempfile.mkdtemp())
        try:
            fn(tmp)
            print(f"  ✓ {name}")
        except AssertionError as e:
            print(f"  ✗ FAIL: {name}\n      {e}")
            fails += 1
        except Exception as e:
            print(f"  ✗ ERROR: {name}\n      {type(e).__name__}: {e}")
            fails += 1
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    print()
    if fails == 0:
        print("✅ All decision_log tests passed.")
    else:
        print(f"❌ {fails} failed.")
        sys.exit(1)
