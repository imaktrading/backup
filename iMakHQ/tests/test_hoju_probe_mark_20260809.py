#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""補URL確証の「🔎 要調査(同じかも)」の回帰テスト (2026-08-09)。

なぜ要るか:
    PSA は同じカードに**複数の印字書式**を使う (OP09-050 ナミの実例: 現物 "ONE PIECE JPN." /
    候補 "ONE PIECE OP09 JP")。書式が違うだけで人が「違う」を押すと **使える仕入元を捨てる**。
    かといって「仕入れる」に倒すと誤変種を掴む。判断を保留したまま印だけ残す受け皿が要る。

不変条件:
  - probes は confirmed / diffs / skip と**混ざらない**
  - probes が無い旧形式の POST でも壊れない (後方互換)
  - 確証UIの HTML に要調査ボタンが候補ごとに出る
  - JS が壊れていない (過去に生の改行混入で script ブロックが全滅した事故がある)
"""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))

import psa_resource_confirm as prc  # noqa: E402


def _item(n=2):
    return [{"idx": 0, "title": "PSA10 ONE PIECE OP09-050 Nami ALT ART",
             "card_no": "OP09-050", "ebay_url": "https://www.ebay.com/itm/1",
             "ref_image": "https://i.ebayimg.com/x.jpg",
             "candidates": [{"url": f"https://jp.mercari.com/item/m{i}", "price": 19800,
                             "title": "PSA10 ナミ"} for i in range(n)],
             "multi_variant": False, "cost_now": 0, "price_now": 0, "siblings": [],
             "psa_label": {"number": "OP09-050", "variety": "ALTERNATE ART",
                           "brand": "ONE PIECE JPN."}}]


def test_probes_are_separated_from_other_marks():
    r = prc.parse_restock_result({
        "confirmed": [{"idx": 0, "urls": ["https://jp.mercari.com/item/m1"]}],
        "diffs": [{"idx": 1, "url": "https://jp.mercari.com/item/m2"}],
        "probes": [{"idx": 2, "url": "https://jp.mercari.com/item/m3"}],
        "skip": 5})
    assert [p["url"] for p in r["probes"]] == ["https://jp.mercari.com/item/m3"]
    # 混ざらない
    assert [d["url"] for d in r["diffs"]] == ["https://jp.mercari.com/item/m2"]
    assert r["confirmed"][0]["urls"] == ["https://jp.mercari.com/item/m1"]
    assert r["skip"] == 5


def test_backward_compatible_without_probes():
    """probes を送らない旧 POST でも例外にならず空で返る。"""
    r = prc.parse_restock_result({"confirmed": [], "diffs": [], "skip": 0})
    assert r["probes"] == []


def test_probe_entries_without_idx_are_dropped():
    r = prc.parse_restock_result({"probes": [{"url": "https://x/1"},
                                             {"idx": 3, "url": "https://x/2"}]})
    assert [p["idx"] for p in r["probes"]] == [3]


def test_html_has_probe_button_per_candidate():
    html = prc.build_restock_html(_item(n=2))
    assert html.count("data-r='probe'") == 2, "候補ごとに要調査ボタンが出ること"
    assert "要調査(同じかも)" in html


def test_js_not_broken_by_raw_newline():
    """script ブロックに生の改行が混じると関数が全滅する (過去事故)。"""
    html = prc.build_restock_html(_item())
    body = re.search(r"<script>(.*?)</script>", html, re.S).group(1)
    for fn in ("function go(", "function setRsn(", "function setAll("):
        assert body.count(fn) == 1, f"{fn} が壊れている"
    # 引用符が行内で閉じていない = リテラルが改行で切れている
    odd = [ln for ln in body.split("\n") if ln.count("'") % 2 or ln.count('"') % 2]
    assert not odd, f"JS の文字列リテラルが行途中で切れている: {odd[:2]}"
    assert "probes:probes" in body, "probes が POST に含まれること"
