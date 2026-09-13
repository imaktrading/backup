# -*- coding: utf-8 -*-
"""外す理由に「仕入元が売り切れ」を足す (2026-09-13 ユーザー指摘)。

    「売り切れの可能性の場合、外す理由に仕入元売り切れがないよ」

理由は3つとも意味が違う。混ぜると後から読めなくなり、センサーが壊れる:
  - 違う         = 検索が別商品を拾った精度事故 (即対応のセンサー)
  - 見送り       = 商品は合っているが今回は買わない (business 判断)
  - 仕入元が売り切れ = URL そのものがもう買えない

売り切れを押した URL は「買えない URL」台帳 (`remember_not_buyable`) に入れる。
`_build_visual_candidates` が既に読んでいる台帳なので、**全ての候補画面から二度と出ない**。
"""
import io
import os
import sys

_TOOLS = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "iMakHQ", "tools"))
sys.path.insert(0, _TOOLS)

import psa_resource_confirm as prc      # noqa: E402
import psa_resource_gate as gate        # noqa: E402


def _src(name):
    return io.open(os.path.join(_TOOLS, name), encoding="utf-8").read()


def test_post_parses_sold_separately():
    """POST の sold は diffs / notpsa / skip のどれにも混ざらない。"""
    res = prc.parse_restock_result({
        "confirmed": [{"idx": 0, "urls": ["https://x/1"]}],
        "diffs": [{"idx": 1, "url": "https://x/2"}],
        "notpsa": [{"idx": 2, "url": "https://x/3"}],
        "sold": [{"idx": 3, "url": "https://snkrdunk.com/apparels/1/used/9"}],
        "skip": 2,
    })
    assert [d["url"] for d in res["sold"]] == ["https://snkrdunk.com/apparels/1/used/9"]
    assert [d["url"] for d in res["diffs"]] == ["https://x/2"]
    assert [d["url"] for d in res["notpsa"]] == ["https://x/3"]
    assert res["skip"] == 2


def test_post_without_sold_is_backward_compatible():
    """旧い画面 (sold を送らない) でも落ちない。"""
    assert prc.parse_restock_result({"confirmed": [], "diffs": [], "skip": 0})["sold"] == []


def test_ui_has_sold_button():
    """画面に理由ボタンが出る (押せなければ意味がない)。"""
    html = prc.build_restock_html([{
        "idx": 0, "itemID": "1", "title": "PSA 10 One Piece OP01-001",
        "ref": "https://i.ebayimg.com/x.jpg",
        "candidates": [{"url": "https://snkrdunk.com/apparels/1/used/9", "channel": "snkrdunk",
                        "price": 7700, "name": "最新の検索に無い (売り切れの可能性)"}],
    }])
    assert "data-r='sold'" in html
    assert "仕入元が売り切れ" in html


def test_page_script_collects_and_sends_sold():
    """ボタンがあっても送らなければ「見送り」に化ける (未選択と同じ扱いになる)。"""
    js = _src("psa_resource_confirm.py")
    assert "else if(ck.dataset.rsn==='sold'){solds.push(" in js
    assert "sold:solds" in js


def test_hoju_records_sold_not_as_skip_and_uses_ledger():
    """補URL③: 出品側は「売り切れ」で記録し、URL は買えない台帳へ入れる。"""
    src = _src("psa_hoju_fill.py")
    assert 'reason = "違う" if idx in diffs else ("売り切れ" if idx in solds else "見送り")' in src
    assert 'remember_not_buyable(_su, "仕入元が売り切れ (補URL③ 目視)")' in src


def test_restock_screen_records_sold_and_uses_ledger():
    """再仕入れ照合 (同じ画面を使う) も同じ扱い。片方だけだと、もう片方から再表示される。"""
    src = _src("psa_resource_gate.py")
    assert 'remember_not_buyable(_su, "仕入元が売り切れ (再仕入れ照合 目視)")' in src
    cands = [{"itemID": str(i), "card_no": "x", "title": "t", "ebay_url": "u"} for i in range(4)]
    out = gate._build_review_skip_rows(cands, {0, 1, 2, 3}, set(), {0}, "2026-09-13", {1}, {2})
    assert [r[3] for r in out] == ["違う", "PSA10でない", "売り切れ", "見送り"]


def test_restock_reason_backward_compatible():
    """sold_idxs 省略時は従来どおり。"""
    cands = [{"itemID": "1", "card_no": "x", "title": "a", "ebay_url": "u"}]
    assert gate._build_review_skip_rows(cands, {0}, set(), set(), "2026-09-13")[0][3] == "見送り"
