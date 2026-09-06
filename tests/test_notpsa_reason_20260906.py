# -*- coding: utf-8 -*-
"""「PSA10でない」を「違う」から分ける (2026-09-06 ユーザー指示)。

「違う」は **検索が別カードを拾った精度事故** を数えるセンサー。グレード違いを混ぜると
数字が濁るうえ、補URL候補NG 経由で 🌱(新規出品の種) に流れ、PSA10限定運用なのに
人がもう一度見て捨てる往復が出ていた。
"""
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "iMakHQ", "tools")))

import psa_resource_confirm as prc      # noqa: E402
import psa_resource_gate as gate        # noqa: E402
import psa_hoju_fill as hf              # noqa: E402


def test_post_parses_notpsa_separately():
    """POST の notpsa は diffs / skip のどちらにも混ざらない。"""
    res = prc.parse_restock_result({
        "confirmed": [{"idx": 0, "urls": ["https://x/1"]}],
        "diffs": [{"idx": 1, "url": "https://x/2"}],
        "notpsa": [{"idx": 2, "url": "https://x/3"}],
        "skip": 4,
    })
    assert [d["url"] for d in res["diffs"]] == ["https://x/2"]
    assert [d["url"] for d in res["notpsa"]] == ["https://x/3"]
    assert res["skip"] == 4


def test_post_without_notpsa_is_backward_compatible():
    """旧い画面 (notpsa を送らない) でも落ちない。"""
    res = prc.parse_restock_result({"confirmed": [], "diffs": [], "skip": 0})
    assert res["notpsa"] == []


def test_ui_has_notpsa_button():
    """画面に4つ目の理由ボタンが出る (押せなければ意味がない)。"""
    html = prc.build_restock_html([{
        "idx": 0, "itemID": "1", "title": "PSA 10 One Piece OP01-001",
        "ref": "https://i.ebayimg.com/x.jpg",
        "candidates": [{"url": "https://jp.mercari.com/item/m1", "site": "mercari", "price": 1000}],
    }])
    assert "data-r='notpsa'" in html
    assert "PSA10でない" in html


def test_notpsa_goes_to_both_ledgers():
    """1クリックが2つの台帳に効く。片方だけだと、もう片方から必ず再表示される。"""
    ng, nc = hf.build_notpsa_rows([{
        "itemID": "358", "cert": "123", "url": "https://jp.mercari.com/item/m9",
        "title": "PSA 10 One Piece OP01-001", "cand_title": "CGC9.5 ルフィ", "cand_price": "3000",
    }], "2026-09-06")
    assert ng == [["358", "123", "https://jp.mercari.com/item/m9",
                   "PSA 10 One Piece OP01-001", "2026-09-06", "CGC9.5 ルフィ", "3000"]]
    assert nc == [["https://jp.mercari.com/item/m9", hf.NOTPSA_REASON,
                   "2026-09-06", "CGC9.5 ルフィ"]]


def test_notpsa_rows_skip_empty_url():
    """URL が無い行は台帳に入れない (キーが無いと除外に効かない)。"""
    ng, nc = hf.build_notpsa_rows([{"itemID": "1", "url": ""}], "2026-09-06")
    assert ng == [] and nc == []


def test_review_skip_reason_distinguishes_notpsa():
    """出品単位の台帳でも「見送り」に化けさせない (後から理由が読めなくなる)。"""
    cands = [{"itemID": "1", "card_no": "OP01-001", "title": "a", "ebay_url": "u1"},
             {"itemID": "2", "card_no": "OP01-002", "title": "b", "ebay_url": "u2"},
             {"itemID": "3", "card_no": "OP01-003", "title": "c", "ebay_url": "u3"}]
    out = gate._build_review_skip_rows(cands, {0, 1, 2}, set(), {0}, "2026-09-06", {1})
    assert [r[3] for r in out] == ["違う", "PSA10でない", "見送り"]


def test_review_skip_reason_backward_compatible():
    """notpsa_idxs 省略時は従来どおり (違う/見送り の2値)。"""
    cands = [{"itemID": "1", "card_no": "x", "title": "a", "ebay_url": "u"}]
    out = gate._build_review_skip_rows(cands, {0}, set(), set(), "2026-09-06")
    assert out[0][3] == "見送り"
