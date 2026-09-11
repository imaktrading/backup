# -*- coding: utf-8 -*-
"""itemID の書き戻しがスニダン仕入の出品も拾うこと (2026-09-11 実害)。

スニダン仕入の出品は SKU = 出品ID (数字だけ / 例 48714850)、仕入元URL =
`snkrdunk.com/apparels/<カード>/used/<出品ID>`。書き戻しの突合キーはメルカリ (m…) と
Amazon (10桁) の形しか持っておらず、出品直後の書き戻しを1回取りこぼすと **二度と拾えなかった**。

実害: SB02-001 を 20:06 に出品 (820113987395) → B列が空のまま → 20:13 の 🤖自動 が
同じ行を「未出品」として選び直し → eBay が重複で拒否 → 1件目で止まる設計なので
**同じ走行の他10件も出品されなかった**。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "tools"))
import itemid_writeback_audit as W     # noqa: E402

SD_URL = "https://snkrdunk.com/apparels/722578/used/48714850"


def _row(url, itemid="", cert=""):
    r = [""] * 20
    r[W.COL_A], r[W.COL_ITEMID], r[W.COL_CERT], r[W.COL_CAT] = url, itemid, cert, "TCG"
    return r


def test_スニダンのSKUが索引に入る():
    _bc, bs = W.build_live_index({"820113987395": {"sku": "48714850", "cur": "USD"}})
    assert bs == {"48714850": "820113987395"}


def test_スニダンの行に書き戻せる():
    _bc, bs = W.build_live_index({"820113987395": {"sku": "48714850", "cur": "USD"}})
    got = W.find_missing([["h"] * 20, _row(SD_URL)], {}, bs, "HIGH")
    assert [(g["row"], g["item_id"]) for g in got] == [(2, "820113987395")]


def test_別の出品IDには当てない():
    _bc, bs = W.build_live_index({"1": {"sku": "48714851", "cur": "USD"}})
    assert W.find_missing([["h"] * 20, _row(SD_URL)], {}, bs, "HIGH") == []


def test_ミラーは今までどおり索引に入れない():
    _bc, bs = W.build_live_index({"9": {"sku": "48714850", "cur": "GBP"}})
    assert bs == {}


def test_既存の形は変わらない():
    bc, bs = W.build_live_index({
        "1": {"sku": "PSA10-153671405", "cur": "USD"},
        "2": {"sku": "m28395383253", "cur": "USD"},
        "3": {"sku": "B0FJQKXN88", "cur": "USD"},
    })
    assert bc == {"153671405": "1"}
    assert bs == {"m28395383253": "2", "B0FJQKXN88": "3"}
