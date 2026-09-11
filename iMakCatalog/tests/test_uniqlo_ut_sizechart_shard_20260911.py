# -*- coding: utf-8 -*-
"""実寸表を複数本で分担する時、行の割り振りが **品番だけで決まる** こと (2026-09-11).

並びの順番 (i % n) で割っていた時、3本を 30秒ずらして起動したら、その間に1本目が
取った分だけ2本目・3本目の番号がずれ、**誰も取らない行が 115行**・2本が取る行ができた。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scrapers"))

import uniqlo_ut_sizechart as S  # noqa: E402

PIDS = [f"E48{n:04d}-000" for n in range(300)]


def test_every_row_goes_to_exactly_one_shard():
    for pid in PIDS:
        assert sum(S._shard_of(pid, 3) == k for k in range(3)) == 1


def test_assignment_does_not_shift_when_other_rows_disappear():
    """他の1本が先に何行か取って対象から消えても、残りの行の担当は変わらない."""
    before = {p: S._shard_of(p, 3) for p in PIDS}
    remaining = PIDS[10:]                 # 1本目が先に10行取った後
    assert all(S._shard_of(p, 3) == before[p] for p in remaining)
