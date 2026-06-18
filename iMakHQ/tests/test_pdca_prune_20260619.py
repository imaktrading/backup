# -*- coding: utf-8 -*-
"""pdca_store.prune_resolved_gaps 回帰テスト (2026-06-19)。

Catalog 指摘B: missing_models の約60%が解決済(catalog に後から収録)なのに pending のまま
毎回 emit_consolidated_request で再発行され Catalog に積む。prune は resolve_fn で解決済を
done 化し「真の未解決のみ」に保つ。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

import pdca_store as pdca


def _mem_con():
    con = pdca.connect(":memory:")
    return con


def _seed(con):
    ts = "2026-06-19"
    # 解決済(catalog収録済)2件 + 真の未解決1件 + 別source(touch対象外)1件
    pdca.upsert_improvement(con, "gshock", "GA-710-1AJF", "catalog_add", "",
                            source="missing_models", layer="A", finding_type="catalog_gap", ts=ts)
    pdca.upsert_improvement(con, "gshock", "DW-5600GL-9JR", "catalog_add", "",
                            source="missing_models", layer="A", finding_type="catalog_gap", ts=ts)
    pdca.upsert_improvement(con, "tcg", "WEIRD-UNRESOLVED-XYZ", "catalog_add", "",
                            source="missing_models", layer="A", finding_type="catalog_gap", ts=ts)
    pdca.upsert_improvement(con, "tcg", "some_md_topic", "catalog_request", "",
                            source="md_import", layer="A", finding_type="catalog_gap", ts=ts)


def test_prune_marks_resolved_done_and_keeps_unresolved():
    con = _mem_con()
    _seed(con)
    resolved = {"GA-710-1AJF", "DW-5600GL-9JR"}
    res = pdca.prune_resolved_gaps(con, lambda cat, iid: iid in resolved, ts="2026-06-19")
    assert res["pruned"] == 2
    assert res["checked"] == 3                 # missing_models のみ対象(md_import 除外)
    pend = {r["item_id"] for r in pdca.list_queue(con, status="pending")}
    assert "WEIRD-UNRESOLVED-XYZ" in pend       # 真の未解決は残る
    assert "some_md_topic" in pend              # 別source は触らない
    assert "GA-710-1AJF" not in pend            # 解決済は落ちた


def test_prune_does_not_touch_other_sources():
    con = _mem_con()
    _seed(con)
    # 全部解決と返す resolve_fn でも source 外(md_import)は対象にならない
    pdca.prune_resolved_gaps(con, lambda cat, iid: True, ts="2026-06-19")
    pend = {r["item_id"] for r in pdca.list_queue(con, status="pending")}
    assert "some_md_topic" in pend


def test_resolve_failure_is_fail_closed_keeps_item():
    con = _mem_con()
    _seed(con)
    def _boom(cat, iid):
        raise RuntimeError("catalog db down")
    res = pdca.prune_resolved_gaps(con, _boom, ts="2026-06-19")
    assert res["pruned"] == 0                   # 判定失敗時は1件も落とさない(誤って未解決を消さない)
    pend = {r["item_id"] for r in pdca.list_queue(con, status="pending")}
    assert "GA-710-1AJF" in pend
