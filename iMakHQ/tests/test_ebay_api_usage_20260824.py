# -*- coding: utf-8 -*-
"""eBay API の1日の呼出回数を数える (2026-08-24 監視くん依頼)。

## なぜ
8/24 11:00 に eBay の1日上限 (エラー518) に当たり、16:00 の回復まで **取下げが1件も
送れなかった**。仕入元が売切なのに買える出品が6件残った (キャンセル → Defect の一歩手前)。

鍵は 8/21 に1本化済みなので **誰か1つが使い切ると全員が止まる**。ところが監視くん以外は
自分の消費を数えておらず、原因を特定できなかった。eBay の使用量照会は廃止済 (HTTP 410) で、
自分で数えるしかない。

★止まるのは取下げ。出品はやり直せるが、取下げ漏れはキャンセルに直結する。
"""
import json
import os
import sys
from datetime import datetime

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for p in (os.path.join(_ROOT, "iMakeBayAPI"), os.path.join(_ROOT, "iMakHQ", "tools")):
    if p not in sys.path:
        sys.path.insert(0, p)


@pytest.fixture(scope="module")
def fx():
    import fix_de_speedpak_shipping
    return fix_de_speedpak_shipping


@pytest.fixture(scope="module")
def U():
    import ebay_api_usage
    return ebay_api_usage


# ── eBay の1日は 日本時間 16:00 区切り ──────────────────────────────
@pytest.mark.parametrize("when,want", [
    (datetime(2026, 8, 24, 15, 59), "2026-08-23"),   # 16時前はまだ前日
    (datetime(2026, 8, 24, 16, 0), "2026-08-24"),    # ここで日が変わる
    (datetime(2026, 8, 24, 9, 0), "2026-08-23"),     # 午前は前日の枠
    (datetime(2026, 8, 24, 23, 30), "2026-08-24"),
])
def test_ebay_day_boundary(fx, when, want):
    assert fx.ebay_day(when) == want


def test_counts_by_call_name(fx, tmp_path):
    p = str(tmp_path / "usage.json")
    now = datetime(2026, 8, 24, 20, 0)
    for name in ("GetItem", "GetItem", "ReviseFixedPriceItem"):
        fx._record_call(name, path=p, now=now)
    got = json.load(open(p, encoding="utf-8"))["2026-08-24"]
    assert got["GetItem"] == 2 and got["ReviseFixedPriceItem"] == 1
    assert got["_total"] == 3


def test_days_are_separate(fx, tmp_path):
    p = str(tmp_path / "usage.json")
    fx._record_call("GetItem", path=p, now=datetime(2026, 8, 24, 15, 0))   # 前日枠
    fx._record_call("GetItem", path=p, now=datetime(2026, 8, 24, 17, 0))   # 当日枠
    got = json.load(open(p, encoding="utf-8"))
    assert got["2026-08-23"]["_total"] == 1 and got["2026-08-24"]["_total"] == 1


def test_old_days_are_pruned(fx, tmp_path):
    p = str(tmp_path / "usage.json")
    for d in range(1, 25):
        fx._record_call("X", path=p, now=datetime(2026, 8, d, 20, 0))
    assert len(json.load(open(p, encoding="utf-8"))) <= 14


def test_counting_never_breaks_the_api_call(fx):
    """数えられなくても API 呼出は止めない (補助なので)。"""
    assert fx._record_call("GetItem", path="Z:/no/such/dir/usage.json") == 0


def test_post_records_every_call(fx):
    """出口が1本なので、そこで数えていること (数え漏れを作らない)。"""
    import inspect
    src = inspect.getsource(fx.post)
    assert "_record_call(callname)" in src


# ── 読み出し側 ────────────────────────────────────────────────────
def test_summary_is_newest_first(U):
    data = {"2026-08-22": {"_total": 5, "GetItem": 5},
            "2026-08-24": {"_total": 9, "GetItem": 7, "ReviseFixedPriceItem": 2},
            "2026-08-23": {"_total": 1, "GetItem": 1}}
    got = U.summarize(data, days=2)
    assert [d for d, _t, _c in got] == ["2026-08-24", "2026-08-23"]
    assert got[0][1] == 9
    assert got[0][2][0] == ("GetItem", 7)      # 多い順


def test_total_is_not_shown_as_a_call_name(U):
    data = {"2026-08-24": {"_total": 3, "GetItem": 3}}
    _d, total, calls = U.summarize(data)[0]
    assert total == 3 and [c for c, _ in calls] == ["GetItem"]


@pytest.mark.parametrize("total,state", [
    (10, "ok"), (2999, "ok"), (3000, "warn"), (4999, "warn"), (5000, "over"), (7000, "over"),
])
def test_verdict_leaves_room_for_takedowns(U, total, state):
    """取下げの枠を食い始めた時点で警告する (上限に当たってからでは遅い)。"""
    assert U.verdict(total)[0] == state
