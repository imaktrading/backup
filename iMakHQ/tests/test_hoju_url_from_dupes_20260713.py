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


def test_primary_with_dead_supply_still_gets_the_url():
    """★2026-08-18 方針転換: primary の D(売り切れ)は **足さない理由にしない**。

    D は仕入元が死んだ印で、eBay の出品が終わった印ではない。
    「eBay に出ているのに仕入元が死んでいる」= 売れたら仕入不能 = キャンセル =
    Defect Rate なので、**そこが一番 補URL を足すべき相手**。
    旧テスト (test_no_live_primary_not_added) はこの逆を固定していた。
    実害: SMP2-014 / SV8a-203 は eBay live + D=○ で、同じカードの生きた仕入元を
    見つけた当日に捨てていた。
    """
    vals = [HEADER,
            _row(itemid="358x", sold="○", cert="c1", key="M3-086"),     # 出品中・仕入元は死亡
            _row(url="https://m/dup1", cert="c2", key="M3-086")]
    plan, _ = compute_additions(vals)
    assert plan[2]["add"] == ["https://m/dup1"]
    assert plan[2]["supply_dead"] is True


def test_ended_listing_is_not_a_primary_when_live_ids_given():
    """eBay に無い itemID は足す先にしない (live cache が SSOT)."""
    vals = [HEADER,
            _row(itemid="358x", cert="c1", key="M3-086"),
            _row(url="https://m/dup1", cert="c2", key="M3-086")]
    assert compute_additions(vals, live_ids={"999"}) == ({}, [])
    plan, _ = compute_additions(vals, live_ids={"358x"})
    assert plan[2]["add"] == ["https://m/dup1"]


def test_missing_cache_does_not_stop_additions():
    """cache が無い時は絞り込まない (足す行為自体は無害なので止めない)."""
    vals = [HEADER,
            _row(itemid="358x", cert="c1", key="M3-086"),
            _row(url="https://m/dup1", cert="c2", key="M3-086")]
    plan, _ = compute_additions(vals, live_ids=None)
    assert plan[2]["add"] == ["https://m/dup1"]


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


def test_走行結果をファイルに残す():
    """画面にしか出ないと『走ったのか止まったのか』が後から分からない (22本 滞留した)。"""
    import io, os
    src = io.open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                               "tools", "hoju_url_from_dupes.py"), encoding="utf-8").read()
    assert "_record(" in src and "hoju_from_dupes_last.json" in src


def test_仕入元切れの補充本数を出す():
    """一番効く数字 (= 売れたら仕入不能だった出品を救った本数) を必ず表示する。"""
    import io, os
    src = io.open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                               "tools", "hoju_url_from_dupes.py"), encoding="utf-8").read()
    assert "urgent" in src and "仕入元が死んでいる出品への補充" in src


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
