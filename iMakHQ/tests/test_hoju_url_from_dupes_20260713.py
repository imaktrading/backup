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


def test_multiple_live_primary_now_picks_one():
    """★2026-08-18 方針転換: 複数 live でも **捨てずに1つ選んで付ける**。

    旧: 「どちらに付けるか決められない」→ 丸ごと skip = 生きた仕入元を捨てていた (49種)。
    新: 渇いている順に1つだけ選ぶ。**全部には付けない** (1本を2出品の予備にすると
        両方売れた時に片方が履行不能になる)。詳細は Test複数live出品にどう付けるか。
    """
    vals = [HEADER,
            _row(itemid="358a", cert="c1", key="M3-086"),               # live 1
            _row(itemid="358b", cert="c2", key="M3-086"),               # live 2(同KEー)
            _row(url="https://m/dup1", cert="c3", key="M3-086")]        # 2枚目
    plan, warns = compute_additions(vals)
    added = [u for v in plan.values() for u in v["add"]]
    assert added == ["https://m/dup1"]
    assert any("live出品 2件" in w for w in warns)


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


def test_書けたか読み直して確かめる():
    """戻り値は『API を呼んだ数』で『入った数』ではない。実測で1行 落ちていた。"""
    from hoju_url_from_dupes import diff_written
    intended = {10: ["a", "b"], 11: ["c"]}
    assert diff_written(intended, {10: ["a", "b"], 11: ["c"]}) == []
    assert diff_written(intended, {10: ["a"], 11: ["c"]}) == [10]
    assert diff_written(intended, {}) == [10, 11]
    assert diff_written({}, {}) == []


def test_書けていない行を要対応として出す():
    import io, os
    src = io.open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                               "tools", "hoju_url_from_dupes.py"), encoding="utf-8").read()
    assert "verify_written(" in src and "要対応" in src
    assert src.index("verify_written(row_to_urls)") > src.index("write_aux_urls(row_to_urls)")


class Test複数live出品にどう付けるか:
    """★2026-08-18: 以前は『どちらに付けるか決められない』で丸ごと捨てていた (49種)。"""

    def _rows(self, aux_a=None, aux_b=None, sold_a="", sold_b=""):
        return [HEADER,
                _row(itemid="358a", sold=sold_a, cert="c1", key="K", aux=aux_a or []),
                _row(itemid="358b", sold=sold_b, cert="c2", key="K", aux=aux_b or []),
                _row(url="https://m/dup1", cert="c9", key="K")]

    def test_渇いている方に付ける(self):
        plan, warns = compute_additions(self._rows(sold_b="○"))
        assert plan[3]["add"] == ["https://m/dup1"]          # row3 = 仕入元が死んでいる方
        assert plan.get(2, {}).get("add", []) == []
        assert any("live出品 2件" in w for w in warns)

    def test_同条件なら予備の少ない方(self):
        plan, _ = compute_additions(self._rows(aux_a=["x", "y"], aux_b=["x"]))
        assert plan[3]["add"] == ["https://m/dup1"]

    def test_それも同じなら行番号順で毎回同じ答え(self):
        for _ in range(3):
            plan, _ = compute_additions(self._rows())
            assert plan[2]["add"] == ["https://m/dup1"]

    def test_1本を2出品には付けない(self):
        """両方売れたら片方 履行不能。dup_guard が消して回っている状態を自分で作らない。"""
        plan, _ = compute_additions(self._rows())
        added = [u for v in plan.values() for u in v["add"]]
        assert added == ["https://m/dup1"]

    def test_2枚目が2本あれば別々の出品に配る(self):
        vals = [HEADER,
                _row(itemid="358a", cert="c1", key="K"),
                _row(itemid="358b", cert="c2", key="K"),
                _row(url="https://m/dup1", cert="c9", key="K"),
                _row(url="https://m/dup2", cert="c8", key="K")]
        plan, _ = compute_additions(vals)
        assert sorted(u for v in plan.values() for u in v["add"]) == \
            ["https://m/dup1", "https://m/dup2"]
        assert all(len(v["add"]) == 1 for v in plan.values() if v["add"])


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
