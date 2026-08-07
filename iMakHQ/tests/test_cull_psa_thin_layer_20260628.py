# -*- coding: utf-8 -*-
"""listing_funnel: PSA10 の在庫切れ品で「impr_total(広告)のみ・実需ゼロ」は
RESTOCK でなく CULL に落ちる回帰テスト (2026-06-28)。

穴: PSA10 OOS が impr_total>0 だけで RESTOCK 判定 → 再仕入れフロー(strict実需ゲート)が
拾わず、CULL にも入らず宙ぶらりん(実データ 211件)。非PSA は従来通り impr_total>0 で RESTOCK。
"""
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools")))
import listing_funnel as lf


def _row(title, **kw):
    base = {"title": title, "qty": 0, "sold_qty": 0, "watch": 0, "sales90": 0,
            "impr": 0, "impr_total": 0.0, "price": 10.0, "trend_price": 0.0}
    base.update(kw)
    return base


def _flags(rows, item):
    c = lf.classify(rows)
    return ("RESTOCK" if item in c["RESTOCK"] else
            "CULL" if item in c["CULL"] else "OTHER")


def test_psa_thin_layer_goes_cull():
    # PSA10 + impr_total(広告)のみ・実需ゼロ → CULL に落ちる
    psa = _row("One Piece Card Game OP08 Nami Alt Art PSA 10", impr_total=50.0)
    assert _flags([psa], psa) == "CULL"


def test_psa_with_real_demand_stays_restock():
    # PSA10 + organic impr(実需) あり → RESTOCK 維持
    psa = _row("Pokemon Charizard PSA 10", impr=3, impr_total=50.0)
    assert _flags([psa], psa) == "RESTOCK"

    psa2 = _row("Pokemon Pikachu PSA 10", watch=2)
    assert _flags([psa2], psa2) == "RESTOCK"


def test_non_psa_impr_total_stays_restock():
    # 非PSA は従来通り impr_total>0 だけで RESTOCK (この変更で壊さない)
    gs = _row("Casio G-Shock GA-2100", impr_total=50.0)
    assert _flags([gs], gs) == "RESTOCK"
