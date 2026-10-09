"""注文の取り込みが Sheets の読み取り上限 (429) で落ちた (2026-10-06 18:27)。読み取りは待って読み直す。"""
from pathlib import Path

SRC = (Path(__file__).resolve().parent.parent / "tools" / "order_purchase_sync.py").read_text(encoding="utf-8")


def test_reads_go_through_quota_retry():
    assert "ws.get_all_values()" not in SRC
    assert SRC.count("_read_with_quota_retry(ws.get_all_values)") == 7   # ★2026-10-09 SpeedPAK の送料の読み直しで +1
