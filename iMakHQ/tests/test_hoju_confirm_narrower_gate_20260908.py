"""目視の対象を絞る: 補が3本以下 + 今より安い候補だけ (2026-09-08 ユーザー確定).

> 補は5枠だけど、残が3になったら発動
> 補もありつつ、最安値入れ替わりつつ、作業も減りつつでは？

実測 (2026-09-08): 候補 987本 → 415本 (4割)。カード 339 → 201。
- 補<5 だと **4本ある札の値段最適化**に目視時間の大半が消えていた
  (追加72本のうち42本が入替 = 既に補が在る札の差し替え)
- 補URLは「主が売れた時に買う先」。今の仕入値(N列)より高い物を押さえても
  その値段で買えば利益が消える。実測で候補の54%が今より高かった
4〜5本の札の最安入替は自動追記 (hoju_url_from_dupes) が担う。
"""
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import psa_hoju_fill as H  # noqa: E402


def test_trigger_is_three_backups_or_fewer():
    assert H.CONFIRM_MAX_BACKUPS == 4, "補<4 = 3本以下で発動"
    assert H.CONFIRM_MAX_BACKUPS < H.AUXN, "満杯(5)より狭いこと"


def test_more_expensive_than_current_cost_is_dropped():
    assert H.candidate_cost_conflicts(9000, 5000, False) is True


def test_cheaper_or_equal_is_kept():
    assert H.candidate_cost_conflicts(3000, 5000, False) is False
    assert H.candidate_cost_conflicts(5000, 5000, False) is False


def test_dead_main_supply_keeps_even_expensive():
    """主URLが売り切れ = 供給ゼロ。高くても押さえる価値がある."""
    assert H.candidate_cost_conflicts(99999, 5000, True) is False


def test_unknown_price_or_cost_is_not_judged():
    """判定材料が無い時は落とさない (fail-open)."""
    assert H.candidate_cost_conflicts(None, 5000, False) is False
    assert H.candidate_cost_conflicts(9000, None, False) is False


def test_reason_is_registered_everywhere():
    assert "all_cost" in H.STOP_REASONS
    assert "all_cost" in H.WAIT_REASONS
    assert "all_cost" in H._REASON_JA
