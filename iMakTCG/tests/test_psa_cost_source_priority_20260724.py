"""仕入コスト取得の優先順位を固定 (2026-07-24)。

契機: DON!! カード(cert 154458065)の出品価格が $279.98 と過大。
真因: HIGH シート N列(SSOT=(M or F)−K)が #REF! で空 → psa_to_csv の従来 `N or F` が
      F列(=取得時の古い価格 ¥23,000)へフォールバック。実際の現価格は M列 ¥14,000。
      仕入¥23,000 → $279.98 と過大 pricing(正: 仕入¥14,000 → $184.98)。
対策: _psa_cost_from_row で N → M(現在価格) → F(取得時) の優先。N が空/#REF! でも
      M(最新)を先に拾う。SSOT 定義が M を F より優先するのと整合。
純関数のみ (DB/network 非依存)。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from psa_to_csv import _psa_cost_from_row


def test_n_ssot_wins_when_present():
    assert _psa_cost_from_row("14000", "14000", "23000") == 14000


def test_don_case_n_empty_uses_current_m_not_stale_f():
    # 実データ: N='', M(現在)='14000', F(取得時・古い)='23000' → M を採用(14000)
    assert _psa_cost_from_row("", "14000", "23000") == 14000


def test_n_ref_error_uses_current_m():
    # N が '#REF!' (数字なし) → M へフォールバック
    assert _psa_cost_from_row("#REF!", "14000", "23000") == 14000


def test_falls_to_f_only_when_n_and_m_both_empty():
    assert _psa_cost_from_row("", "", "23000") == 23000
    assert _psa_cost_from_row("#REF!", "", "23000") == 23000


def test_yen_formatted_parsed():
    assert _psa_cost_from_row("", "¥14,000", "¥23,000") == 14000
    assert _psa_cost_from_row("¥8,900", "", "") == 8900


def test_all_empty_returns_none():
    assert _psa_cost_from_row("", "", "") is None
    assert _psa_cost_from_row("#REF!", "", "") is None
    assert _psa_cost_from_row(None, None, None) is None


def test_regression_never_uses_stale_f_over_current_m():
    # 値上がりケースでも同様に M(現在) を優先: F古い安値を拾って過小(赤字)にしない
    assert _psa_cost_from_row("", "30000", "20000") == 30000
