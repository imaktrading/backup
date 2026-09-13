"""run_harvest_mercari_uniqlo が **落ちても途中まで残す** ことを守る (2026-09-13).

実害: 140件 keep した後に chromedriver が ReadTimeout で落ち、書込が最後だけだったため
**140件が丸ごと消えた**。user 指示「途中で保存するようにしてね / 途中で落ちてやり直しは
やめろよ」を楽天側にしか入れていなかった。
"""
from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.offline

SRC = (Path(__file__).resolve().parents[1]
       / "run_harvest_mercari_uniqlo.py").read_text(encoding="utf-8")


def test_writes_to_sheet_during_the_loop_not_only_at_the_end():
    """5件ごとに書く。最後にまとめて書くだけだと、落ちた時に全部消える."""
    assert "len(pending) >= 5 and _flush(pending)" in SRC


def test_pending_rows_are_written_or_saved_in_finally():
    """落ちても finally で書く。書けなければファイルに退避する (黙って捨てない)."""
    assert "if pending and not _flush(pending):" in SRC
    assert "mercari_uniqlo_unwritten_" in SRC


def test_driver_errors_do_not_kill_the_run():
    """詳細取得の例外は1件の失敗として数え、連続3件で再起動する."""
    assert "detail = mercari_item_detail.fetch_detail(driver, url)" in SRC
    assert "consecutive_fail >= 3" in SRC
    assert "driver = _new_driver()" in SRC


def test_rows_already_in_the_sheet_are_not_fetched_again():
    """回し直しても Vision を二重に払わない."""
    assert 'rej["already_in_sheet"] += 1' in SRC


def test_to_sheet_item_keeps_the_material_columns():
    from run_harvest_mercari_uniqlo import to_sheet_item
    it = to_sheet_item({"url": "https://jp.mercari.com/item/m1", "title": "t",
                        "price_jpy": 2000, "found_by_term": "チェンソーマン",
                        "tag_number": "488002"})
    assert it["found_by_term"] == "チェンソーマン" and it["tag_number"] == "488002"
