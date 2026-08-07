"""Regression: 2026-05-11 PT2 — target_usd ≤ $250 緩和 (≤10件 と OR 評価).

【背景】
≤10件閾値導入後の 5/11 9:09 run で出品 3件のみ → 機会損失大。
無在庫 + Promoted Standard SHOP 原則「出品しないと売れない」+ 低額帯は
焦付きリスク低を考慮し、target_usd ≤ MARKET_GATE_MAX_TARGET_USD ($250)
も緩和条件として OR 追加。

ユーザー判断: ≤10件 OR ≤$250 の OR 条件 (どちらか満たせば緩和).
"""
from __future__ import annotations
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TCG = _REPO_ROOT / "iMakTCG"

# 2026-06-03: psa_to_csv は 2026-05-23 V7 移行で OR 緩和 gate (≤10件 OR ≤$250) を廃止し
# cost-plus always-list (薄商い/市場高/適正/⚠️乖離大) へ刷新。check_csv は旧 OR-gate のまま
# = dual_gate_disagreement 未解決。下記テストは psa 側の旧 OR/AND 契約と GO/保留/NO-GO を
# source grep で検証しており現行 psa と乖離。ゲート SSOT 統一後に書換/復活。
_V7_GATE_XFAIL = pytest.mark.xfail(
    reason="psa_to_csv が V7 cost-plus gate へ移行済 (旧 OR 緩和/GO/NO-GO 契約は廃止)。"
           "dual_gate_disagreement 統一後に書換予定",
    strict=False,
)


def test_threshold_constants_match_between_psa_and_check():
    """両ファイルに MAX_TARGET_USD = 250.0 が同値で存在 (SSOT)."""
    psa_src = (_TCG / "psa_to_csv.py").read_text(encoding='utf-8')
    chk_src = (_TCG / "check_csv.py").read_text(encoding='utf-8')
    assert "MARKET_GATE_MAX_TARGET_USD = 250.0" in psa_src
    assert "MARKET_GATE_MAX_TARGET_USD = 250.0" in chk_src
    # ≤10件 閾値は維持
    assert "MARKET_GATE_MIN_LISTINGS = 10" in psa_src
    assert "MARKET_GATE_MIN_LISTINGS = 10" in chk_src


@_V7_GATE_XFAIL
def test_psa_to_csv_uses_or_condition():
    """psa_to_csv.py の緩和分岐が OR 条件 (出品数 OR target_usd)."""
    src = (_TCG / "psa_to_csv.py").read_text(encoding='utf-8')
    assert "if total <= MARKET_GATE_MIN_LISTINGS or target_usd <= MARKET_GATE_MAX_TARGET_USD:" in src


def test_check_csv_uses_or_condition():
    """check_csv.py の緩和分岐が OR 条件."""
    src = (_TCG / "check_csv.py").read_text(encoding='utf-8')
    assert "if total_count <= MARKET_GATE_MIN_LISTINGS or target_usd <= MARKET_GATE_MAX_TARGET_USD:" in src


@_V7_GATE_XFAIL
def test_relax_branch_distinguishes_three_cases():
    """緩和理由が 3パターン (出品数+target両方 / 出品数のみ / targetのみ) で出力される."""
    psa_src = (_TCG / "psa_to_csv.py").read_text(encoding='utf-8')
    chk_src = (_TCG / "check_csv.py").read_text(encoding='utf-8')
    # 両方 (AND): 件数閾値 と target 閾値 を同時参照する分岐の存在
    assert "if total <= MARKET_GATE_MIN_LISTINGS and target_usd <= MARKET_GATE_MAX_TARGET_USD" in psa_src
    assert "if total_count <= MARKET_GATE_MIN_LISTINGS and target_usd <= MARKET_GATE_MAX_TARGET_USD" in chk_src
    # 出品数のみ理由ラベル
    assert "median 不安定" in psa_src
    assert "median 不安定" in chk_src
    # target のみ理由ラベル
    assert "低額帯" in psa_src
    assert "低額帯" in chk_src


@_V7_GATE_XFAIL
def test_existing_thresholds_preserved():
    """既存の GO/HOLD/NO-GO 分岐は保持 (緩和に該当しない高額+多数出品で発動)."""
    psa_src = (_TCG / "psa_to_csv.py").read_text(encoding='utf-8')
    chk_src = (_TCG / "check_csv.py").read_text(encoding='utf-8')
    assert 'gate_label = "GO"' in psa_src
    assert 'gate_label = "保留"' in psa_src
    assert 'gate_label = "NO-GO"' in psa_src
    assert 'gate_status = "GO"' in chk_src
    assert 'gate_status = "HOLD"' in chk_src
    assert 'gate_status = "NOGO"' in chk_src
