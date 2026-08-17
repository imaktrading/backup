# -*- coding: utf-8 -*-
"""「出せるか」判定 (AP列) の回帰テスト (2026-08-17)。

実害: itemID 空・売切でない 58行のうち出せるのは 13行だけだったのに、シートの見た目が
「候補はまだ沢山ある」に見え、補充の判断を誤らせていた。判定は出品くんの抽出と
**同じ順序**でなければ意味が無いので、順序を固定する。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
from sheet_listable_flag import (classify_row, classify_all, _col_a1,  # noqa: E402
                                OK, SECOND, SAME_CERT, SOLD, MIOKURI, NO_COST,
                                FLAG_HEADER, FLAG_COL)

# 列: A0 url / B1 itemID / D3 売切 / F5 価格 / I8 cert / K10 NO-GO / M12 / N13 / R17 cat / AI34 KEY
def _row(url="https://jp.mercari.com/item/m1", itemid="", sold="", cert="c1",
         no_go="", price_f="¥10,000", price_m="", cost_n="", cat="TCG", key=""):
    r = [""] * 35
    r[0], r[1], r[3], r[5], r[8], r[10], r[12], r[13], r[17], r[34] = (
        url, itemid, sold, price_f, cert, no_go, price_m, cost_n, cat, key)
    return r


def _reason(cert, key, certs, keys):
    """sheet_io.already_listed_reason の最小代役 (順序検証が目的)。"""
    if cert and cert in certs:
        return "cert"
    if key and key in keys:
        return "key"
    return ""


def _c(row, certs=(), keys=()):
    return classify_row(row, set(certs), set(keys), _reason)


def test_出せる行だけがOKになる():
    assert _c(_row()) == OK


def test_判定の対象外は空文字_塗らない():
    assert _c(_row(itemid="358123")) == ""      # 出品済
    assert _c(_row(cert="")) == ""              # cert 無し
    assert _c(_row(url="")) == ""               # URL 無し
    assert _c(_row(cat="バッグ")) == ""          # 別カテゴリ (判定ロジックが違う)


def test_同じ現物が出品中は2枚目より先に出る():
    """cert 一致 = 同じ現物。KEY 一致より強い理由なので先に返す。"""
    row = _row(cert="c9", key="k9")
    assert _c(row, certs=["c9"], keys=["k9"]) == SAME_CERT


def test_2枚目は売切より先に判定される():
    """出品くんは dup 判定を sold より前に置いている (売切の2枚目も2枚目と数える)。"""
    row = _row(sold="○", key="k1")
    assert _c(row, keys=["k1"]) == SECOND


def test_売切_見送り_仕入値なし():
    assert _c(_row(sold="○")) == SOLD
    assert _c(_row(no_go="出品見合せ（仕入高）")) == MIOKURI
    assert _c(_row(price_f="", price_m="", cost_n="")) == NO_COST


def test_仕入値はN_M_Fのどれかがあればよい():
    assert _c(_row(price_f="", price_m="¥9,800")) == OK
    assert _c(_row(price_f="", cost_n="9000")) == OK


def test_classify_all_は見出し行を持ち行数が一致する():
    rows = [["header"], _row(), _row(itemid="358999")]
    out = classify_all(rows, set(), set(), _reason)
    assert out[0] == FLAG_HEADER
    assert len(out) == len(rows)
    assert out[1] == OK and out[2] == ""


def test_書込先はAP列():
    """列がずれると既存列 (AO=売切日時) を壊すので固定する。"""
    assert _col_a1(FLAG_COL) == "AP"
    assert _col_a1(0) == "A" and _col_a1(25) == "Z" and _col_a1(26) == "AA"
