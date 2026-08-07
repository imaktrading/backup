# -*- coding: utf-8 -*-
"""長期未解決の stale 退役 回帰テスト (2026-06-27 K1/K5)。

digest が「catalog依頼/修正で消えない」恒久ノイズ(SWSH Family seen×14 等)で汚れる問題。
- K5: pdca で created_ts が N日より古い pending を 'stale' 化(upsert は 'stale' sticky=再import復活せず)。
- K1: auto_catalog_add で missing_models.csv の古い行(detected_at>30日)を間引き。
(pre-commit が collect する iMakHQ/tests/ に配置)
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(_HERE, "..", "tools")))

import pdca_store as pdca  # noqa: E402
import auto_catalog_add_request as aca  # noqa: E402


# ===================== K5: prune_stale_findings =====================

def _seed(con, item, created, status="pending", source="missing_models"):
    pdca.upsert_improvement(con, "tcg", item, "catalog_add", "",
                            source=source, finding_type="catalog_gap", ts=created)
    # created_ts/status を明示セット(seed)
    con.execute("UPDATE improvement_queue SET created_ts=?, status=? WHERE item_id=?",
                (created, status, item))
    con.commit()


def test_prune_stale_demotes_old_pending_only():
    con = pdca.connect(":memory:")
    _seed(con, "OLD", "2026-06-01")        # 26日前 → stale
    _seed(con, "RECENT", "2026-06-25")     # 2日前 → 残す
    _seed(con, "OLD_DONE", "2026-05-01", status="done")  # done は対象外
    res = pdca.prune_stale_findings(con, "2026-06-27", max_age_days=21)
    assert res["pruned"] == 1
    got = dict((r["item_id"], r["status"]) for r in
               con.execute("SELECT item_id,status FROM improvement_queue"))
    assert got["OLD"] == "stale"
    assert got["RECENT"] == "pending"
    assert got["OLD_DONE"] == "done"       # done は触らない


def test_stale_is_sticky_on_reimport():
    """再 import(upsert)されても 'stale' は pending に戻らない(オシレーション防止)。"""
    con = pdca.connect(":memory:")
    _seed(con, "GAP", "2026-06-01")
    pdca.prune_stale_findings(con, "2026-06-27", max_age_days=21)
    # 翌ラン相当: 同じ model を再 import
    pdca.upsert_improvement(con, "tcg", "GAP", "catalog_add", "",
                            source="missing_models", finding_type="catalog_gap", ts="2026-06-28")
    st = con.execute("SELECT status FROM improvement_queue WHERE item_id='GAP'").fetchone()["status"]
    assert st == "stale"   # done でないので復活しない


def test_prune_stale_bad_today_is_noop():
    con = pdca.connect(":memory:")
    _seed(con, "X", "2026-06-01")
    assert pdca.prune_stale_findings(con, "not-a-date")["pruned"] == 0


# ===================== K1: _prune_old_missing =====================

def test_prune_old_missing_drops_only_aged():
    unique = {
        ("tcg", "A"): {"category": "tcg", "model": "A", "detected_at": "2026-05-01 10:00:00"},  # 古
        ("tcg", "B"): {"category": "tcg", "model": "B", "detected_at": "2026-06-20 10:00:00"},  # 新
    }
    n = aca._prune_old_missing(unique, max_age_days=30, today="2026-06-27")
    assert n == 1
    assert ("tcg", "A") not in unique and ("tcg", "B") in unique
