# -*- coding: utf-8 -*-
"""番号不明の目視候補は catalog_add に載せない (2026-09-05)。

カード番号が無い依頼は catalog 側が「決められません」としか返せない
(実測: シャンクス OP09-001 ほか8刷りが在るのに、番号不明では特定不能で空振り3日連続)。
save() の入口で落として、次回また目視に出す(捨てず・対象外にもしない)。

依頼書: hq/requests/2026-09-05_act_code_proposals_tcg.md 提案3
        hq/requests/2026-09-06_act_code_proposals_tcg.md 提案2(入口)
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(_HERE, "..", "tools")))

import newcand_confirm as N  # noqa: E402


def _item(idx, title="PSA10 シャンクス OP09 001", card_no=""):
    return {"idx": idx, "url": f"https://m/{idx}", "src": "補URL候補NG", "src_itemid": "358_1",
            "src_cert": "111", "price": 9000, "title": title, "card_no": card_no,
            "variants": []}


def test_no_card_number_is_not_sent_to_catalog_add(monkeypatch):
    sent = {}
    ng_written = {}
    monkeypatch.setattr(N, "_append_tab",
                        lambda tab, h, rows: ng_written.setdefault(tab, rows))
    monkeypatch.setattr(N, "already_listed_keys", lambda: set())
    monkeypatch.setattr(N, "live_key_set", lambda: set())
    monkeypatch.setattr(N.sheet_io, "read_tab", lambda tab: [])
    monkeypatch.setattr(N.sheet_io, "write_rows_to_tab", lambda tab, rows: None)
    monkeypatch.setattr(N, "append_missing_models",
                        lambda rows, path=None: sent.setdefault("rows", rows) or len(rows))
    items = [_item(0, card_no="")]
    res = N.save(items, {"picks": [], "catalog_reqs": [0], "outs": [], "holds": [],
                         "card_nos": []})
    assert "rows" not in sent, "番号不明なのに missing_models.csv に依頼を出した"
    assert N.NG_TAB not in ng_written, "対象外として記録した(次回また目視に出るべき=何も記録しない)"
    assert res["catalog"] == 0


def test_card_number_present_still_goes_to_catalog_add(monkeypatch):
    """既存挙動を壊さない: 番号が在る候補は従来どおり依頼する。"""
    sent = {}
    monkeypatch.setattr(N, "_append_tab", lambda *a: None)
    monkeypatch.setattr(N, "already_listed_keys", lambda: set())
    monkeypatch.setattr(N, "live_key_set", lambda: set())
    monkeypatch.setattr(N.sheet_io, "read_tab", lambda tab: [])
    monkeypatch.setattr(N.sheet_io, "write_rows_to_tab", lambda tab, rows: None)
    monkeypatch.setattr(N, "append_missing_models",
                        lambda rows, path=None: sent.setdefault("rows", rows) or len(rows))
    monkeypatch.setattr(N, "catalog_variants", lambda no, db=None: [])   # catalog に無い
    items = [_item(0, card_no="OP09-001")]
    res = N.save(items, {"picks": [], "catalog_reqs": [0], "outs": [], "holds": [],
                         "card_nos": []})
    assert "rows" in sent and len(sent["rows"]) == 1
    assert "OP09-001" in sent["rows"][0][1]
    assert res["catalog"] == 1
