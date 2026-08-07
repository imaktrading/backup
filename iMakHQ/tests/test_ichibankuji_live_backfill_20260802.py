# -*- coding: utf-8 -*-
"""一番くじも live 出品の補URLを無人で貯める (2026-08-02)。

従来の対象は「売り切れ○」= **死んでから**探す事後型だけだった。補URL は仕入元が消えた時の
保険なので、切れてから貯めても保険にならない。実測 (同時点):
    一番くじ live 29件: 補0本 10件(34.5%) / 満杯 1件(3.4%) / 平均1.69本
    PSA      live 225件: 補0本 43件(19.1%) / 満杯 36件(16.0%) / 平均2.36本
差は設計から来ている(PSA は live を毎晩無人で探して積み上げる)。ここを揃える。

★安全上の要: live 行は **出品が生きている**。A列(現supply)/B列(itemID)/D列(売切)/N列(cost)を
  上書きすると eBay 出品との紐付けが切れる(取下げ漏れ・二重出品の芽)。補URLだけ足す。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

import ichibankuji_restock as K


def test_live_row_writes_backup_urls_only():
    """live_thin は A/B/D/N を1本も書かない (壊さない)。"""
    reqs = K.build_restock_reqs({
        10: {"a": "https://new", "b": "111", "aux": ["u1"], "cost": 3000, "kind": "live_thin"}})
    assert reqs == [], f"live 行に書込が発生している: {reqs}"


def test_oos_row_still_writes_everything():
    """OOS は従来どおり A/B/D(/N) を書く (回帰)。"""
    reqs = K.build_restock_reqs({
        10: {"a": "https://new", "b": "111", "aux": ["u1"], "cost": 3000, "kind": "oos"}})
    ranges = [r["range"] for r in reqs]
    assert ranges[:3] == ["A10", "B10", "D10"]
    assert any(r["range"].endswith("10") and r["values"] == [[3000]] for r in reqs)


def test_kind_defaults_to_oos_for_old_callers():
    """kind を持たない呼出(旧 confirmed/保存済JSON)は従来どおり = 後方互換。"""
    reqs = K.build_restock_reqs({7: {"a": "x", "b": "1", "aux": [], "cost": 0}})
    assert [r["range"] for r in reqs] == ["A7", "B7", "D7"]


def test_live_selection_all_goes_to_backup(monkeypatch):
    """live 行は選んだ **全部** が補URL。1本目を A に取ると現supplyを潰す。"""
    urls, cost = K.sort_oks_desc([{"url": "a", "price": 100}, {"url": "b", "price": 300}])
    assert urls[0] == "b" and cost == 300          # 高い順・最高値が cost (既存仕様)
    # live_thin の組み立ては pass_expand 内。ここでは仕様を明文化する回帰点として
    # 「A に入れない/cost を書かない」を build_restock_reqs 側で保証済みなことを確認する。
    assert K.build_restock_reqs({1: {"a": urls[0], "cost": cost, "kind": "live_thin"}}) == []


def test_thin_backup_targets_pick_live_rows_with_few_aux(monkeypatch):
    """live(itemIDあり/売切なし) かつ 補URL < N だけを拾う。"""
    hdr = [""] * 33
    def row(item_id, sold, cat, n_aux):
        r = [""] * 33
        r[1] = item_id
        r[2] = "タイトル"
        r[3] = sold
        r[K.COL_CAT] = cat
        for k in range(K.AUX_COL0, K.AUX_COL0 + n_aux):
            r[k] = "https://x"
        return r

    rows = [hdr,
            row("1", "", "一番くじ", 0),      # 拾う
            row("2", "", "一番くじ", 1),      # 補1本 → 拾わない(max_backups=1)
            row("3", "○", "一番くじ", 0),     # 売り切れ → OOS 側の担当
            row("4", "", "PSA", 0),           # 別カテゴリ
            row("", "", "一番くじ", 0)]       # itemID 無し

    class _WS:
        def get_all_values(self):
            return rows

    monkeypatch.setattr(K.sheet_io, "_product_ws", lambda: _WS())
    monkeypatch.setattr(K, "_load_cooldown", lambda: {})
    got = K.get_thin_backup_ichibankuji(10, max_backups=1)
    assert [g["item_id"] for g in got] == ["1"]
    assert got[0]["kind"] == "live_thin"


def test_prefetch_fills_remaining_slots_with_live(monkeypatch):
    """OOS を先に埋め、余った枠だけ live 薄い分を足す (OOS 優先)。"""
    calls = {}
    monkeypatch.setattr(K, "get_oos_ichibankuji",
                        lambda n: [{"row": 1, "item_id": "o1", "title": "t", "kind": "oos"}])

    def _thin(n, max_backups=1):
        calls["n"] = n
        return [{"row": 2, "item_id": "L1", "title": "t", "kind": "live_thin"}]

    monkeypatch.setattr(K, "get_thin_backup_ichibankuji", _thin)
    monkeypatch.setattr(K, "_identify_scrape", lambda tg, cn: [{"candidates": []} for _ in tg])
    K.pass_prefetch(10, cand_n=10)
    assert calls["n"] == 9, "OOS で埋めた残り枠だけを live に回していない"
