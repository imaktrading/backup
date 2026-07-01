# -*- coding: utf-8 -*-
"""post_psa_review.split_verified: verified_certs 済cert を自動確定→CSV化する回帰テスト
(2026-07-01)。確認OK済なのに毎回 viewer 再浮上→CSV化されないループの再発防止。
"""
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "tools")))
import post_psa_review as pr


def test_ok_chosen_auto_confirmed():
    vc = {
        "150414013": {"choice": "OK", "product_id": "ST01-006_p1"},
        "148328055": {"choice": "CHOSEN", "product_id": "OP01-013_p1"},
    }
    confirmed, viewer = pr.split_verified(["150414013", "148328055"], vc)
    assert confirmed == {"150414013": "ST01-006_p1", "148328055": "OP01-013_p1"}
    assert viewer == []          # 確認済は viewer に出さない=再浮上しない


def test_none_ng_pending_go_viewer():
    vc = {
        "1": {"choice": "NONE", "product_id": ""},       # 該当なし → build しない
        "2": {"choice": "NG", "product_id": "X"},         # NG → build しない
        "3": {"choice": "PENDING", "product_id": "Y"},    # 未確定 → viewer
        "4": {"choice": "OK", "product_id": ""},          # OKだがpid空 → viewer(fail-closed)
    }
    confirmed, viewer = pr.split_verified(["1", "2", "3", "4"], vc)
    assert confirmed == {}
    assert viewer == ["1", "2", "3", "4"]


def test_unverified_goes_viewer():
    confirmed, viewer = pr.split_verified(["999"], {})
    assert confirmed == {} and viewer == ["999"]
