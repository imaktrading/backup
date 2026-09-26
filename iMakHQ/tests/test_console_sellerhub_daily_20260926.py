"""出品くん Console は Seller Hub のレポート取りを1日1回だけ開く (2026-09-26)。"""
import os
import sys

HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HQ, "console"))

import server as S  # noqa: E402


def test_opens_once_per_day():
    assert S.sellerhub_due("", "2026-09-26")
    assert S.sellerhub_due("2026-09-25\n", "2026-09-26")
    assert not S.sellerhub_due("2026-09-26\n", "2026-09-26")


def test_url_carries_the_auto_marker():
    assert S.SELLERHUB_AUTO_URL.endswith("#shg-auto")
