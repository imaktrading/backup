# -*- coding: utf-8 -*-
"""🛒 PSA 再仕入れ ②: Revise の SKU は PSA10-<cert> のまま (仕入元URLを生成に渡さない) (2026-09-15)。

経緯: ② は「仕入URL」列を読んで supply_url を生成に渡す作りだったが、タブの見出しは「確認済仕入URL」で
一度も渡っていなかった (9/15 の入力 json も全件空)。生成側は supply_url から SKU を作る
(メルカリ m… / スニダン出品番号 / 無ければ PSA10-<cert>)。
渡すように直すと SKU が m… に変わり、**出品済 cert を SKU から数える二重出品の門**
(sheet_io.certs_from_skus は PSA10-<cert> しか読まない) を再仕入れの出品がすり抜ける。
仕入元は後から入れ替わるので m… は古くなるが、cert は出品が続く限り変わらない。→ 渡さないと明記する。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import psa_restock_build as b  # noqa: E402
import sheet_io  # noqa: E402


def test_supply_url_is_never_sent_to_generation():
    rows = [{"itemID": "1", "cost": "9000", "supply_url": "https://jp.mercari.com/item/m111",
             "confirmed_url": "https://jp.mercari.com/item/m111"}]
    inp, _ = b.build_restock_input(rows, {"1": "C1"}, {})
    assert inp["certs"] == ["C1"] and inp["supply_url"] == {}


def test_duplicate_gate_only_reads_cert_skus():
    assert sheet_io.certs_from_skus({"a": "PSA10-146280449", "b": "m73494307129"}) == {"146280449"}
