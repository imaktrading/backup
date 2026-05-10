"""Regression: 2026-05-11 check_csv.py が psa_to_csv.py と同じ ≤10 緩和を SSOT で持つ.

【背景】
psa_to_csv.py で MARKET_GATE_MIN_LISTINGS=10 緩和を入れたが、check_csv.py
側に未反映のため dual gate 不一致が再発。CLAUDE.md「check_csv NO-GO 優先」
運用により、psa_to_csv で緩和 GO した商品が check_csv で NO-GO 表示され
入稿可能件数 0 になる事故が発生 (5/11 8:51 run, dual_gate_disagreement.md
の典型ケース)。
"""
from __future__ import annotations
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TCG = _REPO_ROOT / "iMakTCG"


def test_threshold_constant_matches_psa_to_csv():
    """check_csv.py の閾値定数が psa_to_csv.py と完全一致 (SSOT)."""
    psa_src = (_TCG / "psa_to_csv.py").read_text(encoding='utf-8')
    chk_src = (_TCG / "check_csv.py").read_text(encoding='utf-8')
    assert "MARKET_GATE_MIN_LISTINGS = 10" in psa_src
    assert "MARKET_GATE_MIN_LISTINGS = 10" in chk_src


def test_check_csv_has_relax_branch():
    """check_csv.py 内に 出品数 ≤ MARKET_GATE_MIN_LISTINGS の緩和分岐が存在."""
    src = (_TCG / "check_csv.py").read_text(encoding='utf-8')
    assert "if total_count <= MARKET_GATE_MIN_LISTINGS:" in src
    assert 'gate_status = "RELAX"' in src
    assert "🔓 緩和" in src


def test_relax_branch_evaluated_first():
    """check_csv.py 内で 緩和分岐が GO/保留/NO-GO より前 (= 優先評価)."""
    src = (_TCG / "check_csv.py").read_text(encoding='utf-8')
    relax_pos = src.find("if total_count <= MARKET_GATE_MIN_LISTINGS:")
    go_pos = src.find('gate_status = "GO"')
    nogo_pos = src.find('gate_status = "NOGO"')
    assert relax_pos > 0 and go_pos > 0 and nogo_pos > 0
    assert relax_pos < go_pos, "緩和分岐は GO より前"
    assert relax_pos < nogo_pos, "緩和分岐は NO-GO より前"


def test_summary_distinguishes_relax():
    """GATE判定サマリーに 緩和カウント (relax_count) が表示される."""
    src = (_TCG / "check_csv.py").read_text(encoding='utf-8')
    assert "relax_count" in src
    assert "🔓 緩和 {relax_count}" in src
