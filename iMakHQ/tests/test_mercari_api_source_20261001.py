"""メルカリを API で読む (2026-10-01 ユーザー OK)。詳細の判定は今までと同じ規則を通す。"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import mercari_psa_resource as mp  # noqa: E402


def test_api_verdict_same_rules_as_detail_page():
    ok, ship, rev, buy = mp.api_supply_verdict("on_sale", False, 2, 853, 100)
    assert ok and ship == "送料込み" and buy
    assert mp.api_supply_verdict("on_sale", False, 2, 24, 100)[0] is False        # 評価が少ない
    assert mp.api_supply_verdict("on_sale", False, 1, 853, 100)[0] is False       # 着払い
    assert mp.api_supply_verdict("on_sale", True, 2, 853, 100)[0] is False        # オークション
    assert mp.api_supply_verdict("sold_out", False, 2, 853, 100)[0] is False      # 売り切れ
    assert mp.api_supply_verdict("on_sale", False, 2, None, 100)[0] is False      # 評価が取れない = 落とす


def test_source_selection_default_api_and_chrome_switch(tmp_path):
    assert mp.mercari_source_name(str(tmp_path / "none.json")) == "api"
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"source": "chrome"}), encoding="utf-8")
    assert mp.mercari_source_name(str(p)) == "chrome"
