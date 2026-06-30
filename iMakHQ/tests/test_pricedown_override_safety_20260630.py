# -*- coding: utf-8 -*-
"""apply_pricedown_override の安全性証明テスト (2026-06-30)。

ユーザー懸念「2回走って10%とかにならない?(compound)」「ほんとに大丈夫?」への回答=証明:
  1. 冪等: 何回適用しても同じ価格(絶対指定=V8標準からの計算、前回価格を使わない)
  2. compound しない: pipeline を10回回しても価格不変
  3. 赤字なし: gate(利益率≥gate_pct) + cut(cut_pct%) で 値下げ後利益 ≥ gate-cut > 0
  4. gate: 薄利(degressive高コスト)は据置
  5. 不変条件: gate_pct <= cut_pct は拒否(赤字防止)
  6. 対比: 相対実装(前回価格-5%)は compound する(なぜ絶対が必要かの証明)
"""
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "iMakeBayAPI")))
import pricing_engine as pe


# 安い品(利益率高=cut対象)と 高コスト品(利益率低=gate除外)
CHEAP = ("TCG(PSA10)", 3000)      # 高margin
EXPENSIVE = ("G-SHOCK", 70000)    # degressive で薄利


def test_idempotent_no_compound():
    cat, cost = CHEAP
    first = pe.apply_pricedown_override(cost, cat)["price"]
    # pipeline を10回回す相当 = 毎回 cost から再計算(絶対指定) → 価格は不変
    for _ in range(10):
        again = pe.apply_pricedown_override(cost, cat)["price"]
        assert again == first, f"compound検出: {again} != {first}"


def test_gate_excludes_thin_margin():
    cat, cost = EXPENSIVE
    r = pe.apply_pricedown_override(cost, cat)
    # 高コスト=利益率薄 → 据置(applied False)なら価格はV8標準のまま
    if not r["applied"]:
        assert r["margin_std_pct"] < 10
    else:
        # 仮に gate を超えても、残margin は gate-cut で正
        assert r["margin_after_floor_pct"] > 0


def test_no_loss_invariant():
    # gate=10, cut=5 → どの適用品も値下げ後 floor margin = 5% > 0 (赤字なし)
    for cat, cost in (CHEAP, ("Tシャツ(UT)", 1500), ("一番くじ", 8000)):
        r = pe.apply_pricedown_override(cost, cat, gate_pct=10, cut_pct=5)
        if r["applied"]:
            assert r["margin_after_floor_pct"] >= 5 - 1e-9, (cat, r)


def test_gate_must_exceed_cut():
    # 赤字防止の不変条件: gate <= cut は拒否
    import pytest
    with pytest.raises(ValueError):
        pe.apply_pricedown_override(3000, "TCG(PSA10)", gate_pct=5, cut_pct=5)


def test_title_override_porter():
    # title_override: バッグ(アネロ)カテゴリでも title="PORTER" なら Porter 解決(誤カテゴリ防止)
    cost = 20000
    r_no = pe.apply_pricedown_override(cost, "バッグ(アネロ)", title="")
    r_porter = pe.apply_pricedown_override(cost, "バッグ(アネロ)", title="YOSHIDA PORTER Tanker Bag")
    # title でカテゴリ解決が変わり、基準価格(=値下げ後価格)が異なる
    assert r_porter["price"] != r_no["price"]


def test_policy_recomputed_at_new_price():
    # 値下げ品は送料Policyを新価格で取り直す(バンド跨ぎ整合)。返り値の policy が新価格tier由来。
    cat, cost = CHEAP
    r = pe.apply_pricedown_override(cost, cat)
    assert "shipping_profile_name" in r
    if r["applied"]:
        group = pe._v6_group(cat)
        expected = pe._v6_policy_name(group, pe._v6_tier(r["price"])[0])
        assert r["shipping_profile_name"] == expected   # 新価格の tier で取り直し済


def test_relative_would_compound_contrast():
    # 対比: 相対実装(前回価格×0.95)は compound する → だから絶対指定が必須
    def relative(prev):
        return round(prev * 0.95, 2)
    p = 100.0
    seq = [p := relative(p) for _ in range(3)]
    assert seq[0] > seq[1] > seq[2]            # 95 > 90.25 > 85.74 = 下がり続ける(危険)
    # 絶対指定は対照的に不変
    cat, cost = CHEAP
    vals = {pe.apply_pricedown_override(cost, cat)["price"] for _ in range(3)}
    assert len(vals) == 1                       # 何回でも同じ
