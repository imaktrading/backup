# -*- coding: utf-8 -*-
"""台帳の検索語は `PSA10` と `PSA 10` の2本 (2026-09-21)。

`PSA10` だけで取ると `PSA 10` (空白あり) の出品がほぼ全部抜ける。
うちの売れた19件は全部 `PSA 10` 表記で、台帳に1件も入っていなかった。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(r"C:\dev\iMak\iMakHQ", "tools"))

import market_ledger as M  # noqa: E402


def test_検索語は空白ありと空白なしの2本():
    assert "PSA10" in M.KEYWORDS
    assert "PSA 10" in M.KEYWORDS


def test_URLに検索語が入る():
    assert "keywords=PSA+10" in M.build_url("ポケモン", "SOLD", 90, keywords="PSA 10")
    assert "keywords=PSA10" in M.build_url("ポケモン", "SOLD", 90)


def _r(kw, iid="111", sold="1"):
    return {"種別": "Sold", "検索語": kw, "itemId": iid, "期間": "90d", "売れた数": sold}


def test_2本の検索で同じ出品は1行にまとめる():
    # 両方の語を書いた出品は2回入る。2行にすると売れた数が倍に数えられる
    rows, added, updated = M.merge([_r("PSA10")], [_r("PSA 10")])
    assert len(rows) == 1
    assert (added, updated) == (0, 1)


def test_別の出品は別の行():
    rows, added, _ = M.merge([_r("PSA10", "111")], [_r("PSA 10", "222")])
    assert len(rows) == 2 and added == 1


def test_価格で上下を絞る():
    # 上限は 会社の仕入上限7万円 を出品価格にした値。下限は出せない安さを切る
    u = M.build_url("ポケモン", "SOLD", 90, keywords="PSA 10")
    assert f"minPrice={M.PRICE_MIN}" in u and f"maxPrice={M.PRICE_MAX}" in u
    assert (M.PRICE_MIN, M.PRICE_MAX) == (50, 760)



def test_セラーで絞らない代わりに英語版は数えない():
    rows = [
        {"種別": "Sold", "itemId": "1", "タイトル": "PSA 10 Pikachu 173/165 Sv2a Japanese", "売れた数": "2", "平均落札": "$150"},
        {"種別": "Sold", "itemId": "2", "タイトル": "PSA 10 Pikachu 173/165 English 151", "売れた数": "5", "平均落札": "$90"},
    ]
    agg, _ = M.by_card(rows, lang={}, seller={})
    assert sum(a["sold"] for a in agg.values()) == 2      # 英語版の5個は数えない
