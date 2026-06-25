# -*- coding: utf-8 -*-
"""一番くじ expand のペイロード解析 / 高い順pricing / 候補待ちcooldown 回帰テスト (2026-06-25)。

- parse_pick: 新形式 {skip,oks} + 旧形式(str/list)後方互換
- sort_oks_desc: 可候補を高い順、cost=最高値(高い方しか残らなくても赤字回避)、最大6・重複除去
- cooldown: 候補0/見送りは5日 identify に出さない(溜まり込み防止)
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "iMakeBayAPI")))

import ichibankuji_restock as r  # noqa: E402


def test_parse_pick_new_and_legacy():
    assert r.parse_pick({"skip": False, "oks": [{"url": "u", "price": 100}]}) == (False, [{"url": "u", "price": 100}])
    assert r.parse_pick({"skip": True, "oks": []}) == (True, [])
    assert r.parse_pick("uX") == (False, [{"url": "uX", "price": 0}])      # 旧 identify
    assert r.parse_pick(["a", "b"]) == (False, [{"url": "a", "price": 0}, {"url": "b", "price": 0}])  # 旧 expand
    assert r.parse_pick("NONE") == (False, [])
    assert r.parse_pick(None) == (False, [])


def test_sort_oks_desc_highest_first_and_cost():
    urls, cost = r.sort_oks_desc([{"url": "a", "price": 1380}, {"url": "b", "price": 4500}, {"url": "c", "price": 2290}])
    assert urls == ["b", "c", "a"]      # 高い順
    assert cost == 4500                 # 最高値で Revise
    # A列=最高値, 補=残り
    assert urls[0] == "b" and urls[1:] == ["c", "a"]


def test_sort_oks_max6_and_dedupe():
    oks = [{"url": f"u{i}", "price": i * 100} for i in range(8)] + [{"url": "u7", "price": 999}]  # dup u7
    urls, cost = r.sort_oks_desc(oks)
    assert len(urls) == 6              # 主1+補5 = 最大6
    assert len(set(urls)) == len(urls)  # 重複なし
    assert cost == 999                 # 最高値(dup u7 の999)


def test_cooldown_active_and_filter():
    led = {"358": {"until": "2026-07-01"}}
    assert r.cooldown_active(led["358"], "2026-06-25") is True
    assert r.cooldown_active(led["358"], "2026-07-05") is False
    assert r.cooldown_active(None, "2026-06-25") is False
    kept, n = r.filter_cooldown([{"item_id": "358"}, {"item_id": "999"}], led, "2026-06-25")
    assert [k["item_id"] for k in kept] == ["999"] and n == 1


def test_add_cooldown_roundtrip(tmp_path, monkeypatch):
    p = str(tmp_path / "cd.json")
    monkeypatch.setattr(r, "COOLDOWN_FILE", p)
    n = r._add_cooldown(["111", "222"], days=5, today="2026-06-25")
    assert n == 2
    led = r._load_cooldown()
    assert led["111"]["until"] == "2026-06-30"   # +5日
    assert r.cooldown_active(led["222"], "2026-06-25") is True
