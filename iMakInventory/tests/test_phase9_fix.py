"""Phase 9 修正の regression test.

問題1: 早期 abort 廃止 (MAX_CONSEC_FAILURES → MERCARI_RESTART_THRESHOLD)
問題2: O 列を全行更新する仕様 (trabajo 同等)
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ============================================================================
# 問題1: 早期 abort 廃止確認
# ============================================================================
def test_no_max_consec_failures_constant():
    """MAX_CONSEC_FAILURES は廃止済 (Phase 9 早期 abort 廃止対応)."""
    import monitor_listings
    assert not hasattr(monitor_listings, "MAX_CONSEC_FAILURES"), \
        "MAX_CONSEC_FAILURES が残ってる → 早期 abort が再発する恐れ"


def test_mercari_restart_threshold_exists():
    """mercari driver 自動再起動の閾値 (anti-bot recovery) が定義されている."""
    import monitor_listings
    assert hasattr(monitor_listings, "MERCARI_RESTART_THRESHOLD")
    assert isinstance(monitor_listings.MERCARI_RESTART_THRESHOLD, int)
    assert monitor_listings.MERCARI_RESTART_THRESHOLD >= 1


def test_monitor_listings_has_no_early_abort_break():
    """monitor_listings.process_sheet 内に '連続失敗' での break 文がない.

    旧コードに `if consec_failures >= MAX_CONSEC_FAILURES: break` があったが
    Phase 9 で削除済。コード上 (コメントを除いた) 参照が残っていないか確認。
    """
    import re
    src = (ROOT / "monitor_listings.py").read_text(encoding="utf-8")
    # コメント行 (# で始まる行) を除外してから検索
    code_lines = [
        ln for ln in src.splitlines()
        if not ln.lstrip().startswith("#")
    ]
    code_only = "\n".join(code_lines)
    # 旧 abort カウンタへの代入・参照 がコード上に残っていない
    assert not re.search(r"\bMAX_CONSEC_FAILURES\b", code_only), \
        "MAX_CONSEC_FAILURES への code 参照が残ってる"
    assert "consec_failures >= " not in code_only, \
        "旧 break 比較式が code 上に残ってる"


# ============================================================================
# 問題2: O 列を全行更新 (o_only=True 対応)
# ============================================================================
def test_update_listings_sold_marks_supports_o_only():
    """o_only=True で D 列を skip して O 列のみ書込."""
    from sheet_updater import update_listings_sold_marks
    ws = MagicMock()
    ws.batch_update = MagicMock()

    updates = [
        {"row_index": 5, "checked_at": "2026/04/30 14:00:00", "o_only": True},
    ]
    res = update_listings_sold_marks(ws, updates)

    assert res["updated"] == 1
    assert res["d_writes"] == 0
    assert res["o_writes"] == 1
    # batch_update に渡された cell_updates を確認
    args, _ = ws.batch_update.call_args
    cells = args[0]
    # D 列 update がない
    ranges = [c["range"] for c in cells]
    assert "D5" not in ranges
    assert "O5" in ranges


def test_update_listings_sold_marks_default_writes_d_and_o():
    """o_only 省略時は D + O 両方更新 (従来動作維持)."""
    from sheet_updater import update_listings_sold_marks
    ws = MagicMock()
    ws.batch_update = MagicMock()

    updates = [
        {"row_index": 7, "is_sold": True, "checked_at": "2026/04/30 14:00:00"},
    ]
    res = update_listings_sold_marks(ws, updates)

    assert res["updated"] == 1
    assert res["d_writes"] == 1
    assert res["o_writes"] == 1
    args, _ = ws.batch_update.call_args
    cells = args[0]
    ranges = [c["range"] for c in cells]
    assert "D7" in ranges
    assert "O7" in ranges
    # D 列に "○" 書込 (is_sold=True)
    d_cell = next(c for c in cells if c["range"] == "D7")
    assert d_cell["values"] == [["○"]]


def test_update_listings_sold_marks_mixed_o_only_and_full():
    """同一 batch で o_only と D+O が混在しても正しく処理される.

    Phase 9 の monitor_listings は「変化行 = D+O / 変化なし行 = O_only」で
    複数 update を 1 batch に積むため、これが正しく動くことが必須。
    """
    from sheet_updater import update_listings_sold_marks
    ws = MagicMock()
    ws.batch_update = MagicMock()

    updates = [
        {"row_index": 2, "is_sold": True, "checked_at": "t1"},   # D + O
        {"row_index": 3, "checked_at": "t1", "o_only": True},    # O only
        {"row_index": 4, "is_sold": False, "checked_at": "t1"},  # D + O
        {"row_index": 5, "checked_at": "t1", "o_only": True},    # O only
    ]
    res = update_listings_sold_marks(ws, updates)

    assert res["updated"] == 4
    assert res["d_writes"] == 2  # row 2, 4
    assert res["o_writes"] == 4  # 全行
    args, _ = ws.batch_update.call_args
    cells = args[0]
    ranges = sorted(c["range"] for c in cells)
    # D 列は 2, 4 のみ。O 列は全て。
    assert ranges == sorted(["D2", "O2", "O3", "D4", "O4", "O5"])


def test_update_listings_sold_marks_empty_returns_zero():
    """updates 空でも正常 (新 return キー含む)."""
    from sheet_updater import update_listings_sold_marks
    ws = MagicMock()
    res = update_listings_sold_marks(ws, [])
    assert res["updated"] == 0
    assert res["d_writes"] == 0
    assert res["o_writes"] == 0


def test_monitor_listings_uses_o_only_for_unchanged_rows():
    """monitor_listings.py の updates 構築で error/変化なし行に o_only=True を付与.

    grep で構造的に確認 (実装が変わっても spec 維持確認の anchor)。
    """
    src = (ROOT / "monitor_listings.py").read_text(encoding="utf-8")
    # 「変化なし → o_only」が含まれるブロック
    assert '"o_only":     True' in src
    # コメントで Phase 9 仕様の記述がある
    assert "trabajo 同等" in src or "全件更新" in src or "O 列全件" in src or "全行" in src


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
