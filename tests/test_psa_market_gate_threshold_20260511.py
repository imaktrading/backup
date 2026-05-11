"""Regression: 2026-05-11 PSA TCG 出品数 ≤ 10 件で median gate skip.

【背景】
ユーザー提案: 出品数 ≤ 10 件 = 薄商い、median 不安定 → gate skip で出品継続.
出品数 11+ 件 = 市場成熟、median 信頼 → 通常 GO/保留/NO-GO 判定 (現状維持).

5/11 8:04 run の 8 件で適用シミュレーション:
  Umbreon Ex(78件)/Snorlax Gx(20)/Garchomp Ex(17)/Wigglytuff Art(67)/
    Exeggutor Art(37)/Piplup Art(74) → 維持 (NO-GO 6 件)
  Gyarados Ex(9件)/Trafalgar Law(4) → 緩和 (出品 2 件)
"""
from __future__ import annotations
import importlib.util
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TCG = _REPO_ROOT / "iMakTCG"


def test_threshold_constant_is_10():
    """MARKET_GATE_MIN_LISTINGS = 10 (ユーザー指定値). source 直読み (module load 重い回避)."""
    src = (_TCG / "psa_to_csv.py").read_text(encoding='utf-8')
    assert "MARKET_GATE_MIN_LISTINGS = 10" in src


def test_source_has_threshold_skip_logic():
    """source 内に 出品数 ≤ MARKET_GATE_MIN_LISTINGS の skip 分岐が存在 (OR 条件で target_usd と組合せ)."""
    src = (_TCG / "psa_to_csv.py").read_text(encoding='utf-8')
    # 5/11 PT2 で OR 条件化: target_usd ≤ MARKET_GATE_MAX_TARGET_USD も同時評価
    assert "if total <= MARKET_GATE_MIN_LISTINGS or target_usd <= MARKET_GATE_MAX_TARGET_USD:" in src
    # 緩和ラベル、コストプラス価格採用
    assert '"緩和"' in src
    assert "🔓 緩和" in src


def test_source_preserves_existing_gate_branches():
    """副作用ゼロ: 既存の GO/保留/NO-GO ロジックは維持 (出品 11+ 件で動く)."""
    src = (_TCG / "psa_to_csv.py").read_text(encoding='utf-8')
    # GO 分岐
    assert 'gate_label = "GO"' in src
    # 保留 分岐
    assert 'gate_label = "保留"' in src
    # NO-GO 分岐 + skip_certs.add
    assert 'gate_label = "NO-GO"' in src
    assert 'skip_certs.add(cert)' in src


def test_threshold_skip_branches_evaluated_first():
    """source 内で 出品数閾値 skip が GO/保留/NO-GO 分岐より前 (= 優先評価)."""
    src = (_TCG / "psa_to_csv.py").read_text(encoding='utf-8')
    threshold_pos = src.find("if total <= MARKET_GATE_MIN_LISTINGS:")
    go_pos = src.find('gate_label = "GO"')
    assert threshold_pos > 0 and go_pos > 0
    assert threshold_pos < go_pos, "閾値 skip 分岐は GO 分岐より前にあるべき"
