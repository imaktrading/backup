"""補URL消込 mismatch の告知範囲 regression test.

★ 2026-08-13 制定。実害: 18:49 に「compare-and-clear mismatch 1件 = 要対応」の desktop
ALERT が出たが、中身は **HQ が別の生きた仕入元URLに差し替えただけ** (row1348 slot1)。
監視が売切と確認した URL は既にセルから消えており、消さなかったのが正解。次 cycle が
新URLを普通に見るので、人が何もすることがない。対処不能な通知を鳴らすと、本当に見るべき
通知まで無視されるようになる。

仕様:
- セル値が「別の有効な URL」= HQ 差替 → 告知しない (ログには残す)
- セル値が空 / URL でない → 従来どおり要対応として告知する
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import run_cycle as rc  # noqa: E402


@pytest.mark.offline
def test_hq_url_swap_is_benign():
    m = {"row_index": 1348, "slot": 1,
         "expected_url": "https://jp.mercari.com/shops/product/OLD_SOLD",
         "actual": "https://jp.mercari.com/shops/product/NEW_ALIVE"}
    assert rc._is_benign_url_swap(m) is True


@pytest.mark.offline
def test_empty_cell_is_not_benign():
    """セルが空 = 差替ではない (誰かが消した/取りこぼし) → 告知対象のまま."""
    m = {"row_index": 1, "slot": 0,
         "expected_url": "https://jp.mercari.com/item/m1", "actual": ""}
    assert rc._is_benign_url_swap(m) is False


@pytest.mark.offline
def test_non_url_cell_is_not_benign():
    """URL でない値が入っている = 想定外 → 告知対象のまま."""
    m = {"row_index": 1, "slot": 0,
         "expected_url": "https://jp.mercari.com/item/m1", "actual": "売切"}
    assert rc._is_benign_url_swap(m) is False


@pytest.mark.offline
def test_same_url_is_not_benign_swap():
    """expected と同値なら差替ではない (そもそも mismatch にならない想定の防御)."""
    u = "https://jp.mercari.com/item/m1"
    assert rc._is_benign_url_swap({"expected_url": u, "actual": u}) is False


@pytest.mark.offline
def test_alert_gate_still_fires_for_real_mismatch():
    """HOLD 無し + 要対応 mismatch 1件 なら従来どおり発報判定が立つ."""
    assert rc._should_emit_backup_clear_alert(0, 1) is True
