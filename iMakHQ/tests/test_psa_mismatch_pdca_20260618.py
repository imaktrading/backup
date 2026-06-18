# -*- coding: utf-8 -*-
"""PSA再仕入れ 不一致PDCA reconcile の回帰テスト (2026-06-18)。

真因: KEY解決済(itemID join / 過去目視)で確認ゲートを auto-skip した行が
reconcile に confirmed として渡されず、台帳で永久に「未対処」のまま Catalog へ
毎日同じ依頼を再発行していた (psa_resource_gate._run_mismatch_pdca に auto_idx を
渡し忘れ)。修正: auto_idx 由来の itemID も confirmed_itemids に含める。

ここでは reconcile() レベルで「過去 未対処の catalog 行が、今回 confirmed に入れば
解決へ遷移し、Catalog修正依頼の対象(route_buckets catalog)から外れる」ことを固定する。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

import psa_mismatch_pdca as pdca


def _prev_open_catalog_row(iid="358434565176", key="P-041"):
    """前回台帳: catalog 原因で 未対処 の1行。"""
    return [{
        "初出日": "2026-06-15", "最終検知日": "2026-06-17", "status": "未対処",
        "再発回数": "3", "原因": "catalog", "振り分け先": "Catalog修正依頼",
        "itemID": iid, "cert#": "", "KEY": key, "card_no": "P-041",
        "title": "PSA 10 One Piece Promo #041", "現物PSA_URL": "", "catalog_URL": "",
        "ebay_url": f"https://www.ebay.com/itm/{iid}",
    }]


def test_keyresolved_autoskip_closes_open_ledger():
    """KEY解決済で今回 confirmed(auto_idx相当)に入った行は「解決」へ遷移する。"""
    prev = _prev_open_catalog_row()
    # 今回: rejects 無し / confirmed に当該 itemID(=auto-skipで解決済) を渡す
    ledger, st = pdca.reconcile(prev, rejects=[],
                                confirmed_itemids={"358434565176"}, today="2026-06-18")
    row = next(r for r in ledger if r["itemID"] == "358434565176")
    assert row["status"] == "解決"
    assert st["resolved"] == 1
    assert st["open"] == 0


def test_resolved_row_not_reissued_to_catalog():
    """解決済になった行は route_buckets(catalog) に出ない = Catalog再発行されない。"""
    prev = _prev_open_catalog_row()
    ledger, _ = pdca.reconcile(prev, rejects=[],
                               confirmed_itemids={"358434565176"}, today="2026-06-18")
    buckets = pdca.route_buckets(ledger)
    assert not buckets.get("catalog")  # 再発行ゼロ


def test_open_without_confirmation_still_reissues():
    """逆条件(回帰の対): confirmed に入らなければ 未対処のまま = 再発行され続ける。

    修正前のバグ状態を再現。auto_idx を渡さないと confirmed_itemids が空になり、
    解決へ遷移せず Catalog 依頼が再生成される。
    """
    prev = _prev_open_catalog_row()
    ledger, st = pdca.reconcile(prev, rejects=[],
                                confirmed_itemids=set(), today="2026-06-18")
    assert st["resolved"] == 0
    assert st["open"] == 1
    assert len(pdca.route_buckets(ledger).get("catalog") or []) == 1
