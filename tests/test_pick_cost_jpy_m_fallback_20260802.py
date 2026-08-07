# -*- coding: utf-8 -*-
"""pick_cost_jpy に M列(現在価格)フォールバックを追加した回帰テスト (2026-08-02)。

契機: offer_calc が N列(#REF!/空)を直読みして cost=0 を返し、赤字オファーを承諾
      しかねなかった (BRAVO 依頼書 2026-08-02_offer_calc_cost_and_dest_consult)。
      psa_to_csv._psa_cost_from_row は N→M→F 順で対策済 (2026-07-24) だが、
      pick_cost_jpy は N→F のまま(M を見ない) = 三様問題。

対策: pick_cost_jpy に m_idx=12 を追加、N→M→F 順に統合。全 5 listing scripts +
      psa_to_csv + offer_calc が同一定義になる。

守る不変条件:
  - N が数値なら N (SSOT)
  - N が空/#REF! で M が数値なら M (最新観測値・値下がり後の現価格)
  - N/M 共に空 なら F (取得時価格)
  - 全空 なら "" (int変換で 0 になる呼出側で「該当なし」判定)
  - K (ポイント) は reader 側で控除しない (二重控除防止)

純関数のみ (シート I/O 非依存)。
"""
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "iMakeBayAPI")))
from listing_common import pick_cost_jpy  # noqa: E402


def _row(f="", m="", n=""):
    """商品管理シート行の最小構成 (F=idx5 / M=idx12 / N=idx13)。"""
    r = [""] * 14
    r[5], r[12], r[13] = f, m, n
    return r


# -------------------------------------------------- 優先順 (SSOT 定義通り)
def test_n_wins_when_present():
    assert pick_cost_jpy(_row(f="23000", m="14000", n="14000")) == "14000"


def test_n_empty_falls_to_m():
    """★本命: DON!! カード同型 — N空+M有(値下がり後)→ M を採用。"""
    assert pick_cost_jpy(_row(f="23000", m="14000", n="")) == "14000"


def test_n_ref_error_falls_to_m():
    """N='#REF!' → 数字なし → M へ。ARRAYFORMULA が壊れた時の生存経路。"""
    assert pick_cost_jpy(_row(f="23000", m="14000", n="#REF!")) == "14000"


def test_n_and_m_empty_falls_to_f():
    assert pick_cost_jpy(_row(f="23000", m="", n="")) == "23000"


def test_n_ref_and_m_empty_falls_to_f():
    assert pick_cost_jpy(_row(f="23000", m="", n="#REF!")) == "23000"


def test_all_empty_returns_empty_string():
    assert pick_cost_jpy(_row()) == ""


# -------------------------------------------------- 数字抽出 (¥/, 除去)
def test_yen_formatted_parsed():
    assert pick_cost_jpy(_row(f="", m="¥14,000", n="")) == "14000"
    assert pick_cost_jpy(_row(f="¥23,000", m="", n="")) == "23000"


# -------------------------------------------------- 呼出互換 (既定引数)
def test_default_indices_match_sheet_layout():
    """既定 f_idx=5 / m_idx=12 / n_idx=13 = 商品管理シート F/M/N と一致。"""
    r = ["url", "iid", "title", "", "新品", "23000", "", "", "", "", "", "cid", "14000", "13000"]
    assert pick_cost_jpy(r) == "13000"                                       # N が最強
    r2 = ["url", "iid", "title", "", "新品", "23000", "", "", "", "", "", "cid", "14000", ""]
    assert pick_cost_jpy(r2) == "14000"                                      # N空 → M
    r3 = ["url", "iid", "title", "", "新品", "23000", "", "", "", "", "", "cid", "", ""]
    assert pick_cost_jpy(r3) == "23000"                                      # 両空 → F


# -------------------------------------------------- psa_to_csv wrapper が同じ判定
def test_psa_wrapper_agrees_with_pick_cost_jpy():
    """★三様問題の解消: _psa_cost_from_row と pick_cost_jpy が同じ結論を出す。"""
    sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "iMakTCG")))
    from psa_to_csv import _psa_cost_from_row  # noqa: E402
    cases = [
        ("14000", "14000", "23000"),
        ("",       "14000", "23000"),
        ("#REF!",  "14000", "23000"),
        ("",       "",      "23000"),
        ("",       "",      ""),
    ]
    for n, m, f in cases:
        wrap = _psa_cost_from_row(n, m, f)
        core = pick_cost_jpy(_row(f=f, m=m, n=n))
        expect = int(core) if core else None
        assert wrap == expect, f"三様: wrapper={wrap} / core={core} for (N={n},M={m},F={f})"
