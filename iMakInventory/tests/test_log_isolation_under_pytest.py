"""pytest 実行時のログ隔離 regression test.

★ 2026-08-13 制定。実害: test が本番ログ (logs/listings_YYYY-MM-DD.log) に書き込むため、
「最近エラーが多い」の調査でログを数えると **テスト由来のエラーが本番の異常に見えた**。
実測 08-12: driver crash 系 36 件中 34 件が [TEST] シート (= pytest) 由来、実シートは 2 件。
ログが健全性の判断材料である以上、テストの書込は物理的に分ける。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.mark.offline
def test_log_path_is_separated_under_pytest():
    """pytest 実行中は TESTRUN ログに書く (本番ログを汚さない)."""
    from monitor_listings import _log_path
    p = _log_path()
    assert "TESTRUN" in p.name, f"本番ログに書きに行っている: {p.name}"


@pytest.mark.offline
def test_log_path_is_production_when_not_under_pytest():
    """本番 (PYTEST_CURRENT_TEST 無し) では従来どおり日次ログに書く."""
    from monitor_listings import _log_path
    env = {k: v for k, v in os.environ.items() if k != "PYTEST_CURRENT_TEST"}
    with patch.dict(os.environ, env, clear=True):
        p = _log_path()
    assert "TESTRUN" not in p.name
    assert p.name.startswith("listings_")


@pytest.mark.offline
def test_log_writes_go_to_testrun_file():
    """実際に log() を呼んでも本番ログの mtime が動かない."""
    from monitor_listings import log, _log_path, LOG_DIR
    from datetime import datetime
    prod = LOG_DIR / f"listings_{datetime.now().strftime('%Y-%m-%d')}.log"
    before = prod.stat().st_mtime if prod.exists() else None
    log("regression: この行は本番ログに出てはいけない")
    assert "TESTRUN" in _log_path().name
    if before is not None:
        assert prod.stat().st_mtime == before
