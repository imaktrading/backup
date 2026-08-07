# -*- coding: utf-8 -*-
"""一番くじ expand の 状態/送料 判定 回帰テスト (2026-06-25)。

真因: mercari は1ページに送料込み/着払い・各状態語が UI/関連商品で**常に両方**出るため、
全ページ grep は誤判定(着払いが新品+送料込みフィルタを漏れ通過した)。
『商品の状態』『配送料の負担』の**直後の値だけ**見ることを固定する。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "iMakeBayAPI")))

import ichibankuji_restock as r  # noqa: E402


def test_freeship_item_with_buyer_pays_noise():
    """商品は新品+送料込み。ページに関連商品の『着払い』が混在しても 送料込み と判定。"""
    s = ("関連商品 着払い(購入者負担) ... "
         "<div>商品の状態</div><div>新品、未使用</div> "
         "<div>配送料の負担</div><div>送料込み(出品者負担)</div> "
         "もっと見る 着払い")
    assert r._parse_cond_ship(s) == ("新品、未使用", "送料込み")


def test_buyer_pays_item_excluded():
    """商品が着払い。ページに『送料込み』が他所に在っても 着払い と判定(=フィルタで除外される)。"""
    s = ("この商品は送料込み(出品者負担)のみ… "
         "<div>商品の状態</div><div>目立った傷や汚れなし</div> "
         "<div>配送料の負担</div><div>着払い(購入者負担)</div>")
    cond, ship = r._parse_cond_ship(s)
    assert ship == "着払い"
    assert cond == "目立った傷や汚れなし"
    # フィルタ条件(新品 かつ 送料込み)を満たさない
    assert not (cond in r._KEEP_COND and ship == "送料込み")


def test_no_labels_failclosed():
    """ラベルが無ければ ('','') → フィルタで除外(推測しない)。"""
    assert r._parse_cond_ship("送料込み 着払い 新品、未使用 だけある") == ("", "")


def test_freeship_new_passes_filter():
    s = "商品の状態 未使用に近い 配送料の負担 送料込み"
    cond, ship = r._parse_cond_ship(s)
    assert cond in r._KEEP_COND and ship == "送料込み"
