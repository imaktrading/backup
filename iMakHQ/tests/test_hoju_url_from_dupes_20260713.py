#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""補URL 自動追記 compute_additions の回帰テスト (2026-07-13)。

弾かれた2枚目(B空・同KEー既出品)の A列URL を primary 補URL に既存保持+冪等追加。
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
from hoju_url_from_dupes import compute_additions, AUX0, AUXN, KEY as KEY_COL

# 列: A0=url B1=itemID ... D3=sold ... I8=cert ... AC28..AG32=補URL ... AI34=KEY
def _row(url="", itemid="", sold="", cert="", key="", aux=None):
    r = [""] * 40
    r[0], r[1], r[3], r[8], r[34] = url, itemid, sold, cert, key
    for k, u in enumerate(aux or []):
        r[AUX0 + k] = u
    return r

HEADER = ["h"] * 40


def test_dupe_added_to_live_primary():
    vals = [HEADER,
            _row(itemid="358x", cert="c1", key="M3-086", aux=[]),        # primary(live)
            _row(url="https://m/dup1", cert="c2", key="M3-086")]         # 2枚目(B空)
    plan, warns = compute_additions(vals)
    assert 2 in plan and plan[2]["add"] == ["https://m/dup1"]
    assert not warns


def test_idempotent_skip_if_already_present():
    vals = [HEADER,
            _row(itemid="358x", cert="c1", key="M3-086", aux=["https://m/dup1"]),  # 既に収載
            _row(url="https://m/dup1", cert="c2", key="M3-086")]
    plan, _ = compute_additions(vals)
    assert plan[2]["add"] == [] and plan[2]["skip"] == ["https://m/dup1"]


def test_full_slots_overflow_warns_no_add():
    vals = [HEADER,
            _row(itemid="358x", cert="c1", key="M3-086", aux=["a", "b", "c", "d", "e"]),  # 満杯5
            _row(url="https://m/dup1", cert="c2", key="M3-086")]
    plan, warns = compute_additions(vals)
    assert 2 not in plan or plan[2]["add"] == []
    assert any("満杯" in w for w in warns)


def test_sold_dupe_not_added():
    # 2枚目 の D='○'(売切=供給死) → 補URLに入れない
    vals = [HEADER,
            _row(itemid="358x", cert="c1", key="M3-086", aux=[]),                 # primary(live)
            _row(url="https://m/dup1", sold="○", cert="c2", key="M3-086")]        # 売切2枚目
    plan, _ = compute_additions(vals)
    assert plan == {}


def test_no_live_primary_not_added():
    # KEY を持つ live 行が無い(primary が売切=D非空のみ) → 追加しない
    vals = [HEADER,
            _row(itemid="358x", sold="○", cert="c1", key="M3-086"),     # sold(live扱いでない)
            _row(url="https://m/dup1", cert="c2", key="M3-086")]
    plan, _ = compute_additions(vals)
    assert plan == {}


def test_multiple_live_primary_ambiguous_skip():
    vals = [HEADER,
            _row(itemid="358a", cert="c1", key="M3-086"),               # live 1
            _row(itemid="358b", cert="c2", key="M3-086"),               # live 2(同KEー)
            _row(url="https://m/dup1", cert="c3", key="M3-086")]        # 2枚目
    plan, warns = compute_additions(vals)
    assert all(v["add"] == [] for v in plan.values())
    assert any("複数" in w for w in warns)


def test_urlkey_and_missing_fields_ignored():
    vals = [HEADER,
            _row(itemid="358x", cert="c1", key="item:123"),            # url-key = 対象外
            _row(url="https://m/dup1", cert="c2", key="item:123"),
            _row(url="https://m/dup2", cert="c3", key="")]              # KEー空 = 対象外
    plan, _ = compute_additions(vals)
    assert plan == {}


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
