"""番号は合っているが **刷りが違う** 候補を目視に出さない (2026-09-07).

> 🚨「違う」5件 = 検索が別カード/別変種を拾った精度事故

3走行で 15件中 1 / 5 / 4件が「違う」だった。外された候補を数えたら、番号の門は通るのに
**パラレル (通常の札にパラレル、逆も)** が大半 (実測: NG記録 407件中 38件)。
番号では捕まらないので、刷りの語で外す。
"""
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import psa_hoju_fill as H  # noqa: E402


def test_parallel_candidate_for_normal_card_is_dropped():
    assert H.candidate_variant_conflicts(
        "【PSA10】ポートガス・D・エース (L) {赤} <OP03-001>",
        "PSA10 ポートガス・D・エース(OP03-001)[L-P］リーダーパラレル") is True


def test_one_way_only_ours_parallel_is_kept():
    """こちらがパラレルの時は外さない (★ / -P / SP と表記ゆれが多く、取りこぼすと供給を捨てる)."""
    for ours in ("【PSA10】そげキング(SEC★)", "ゾロ SEC-P", "ルフィ (SP)", "エース パラレル"):
        assert H.candidate_variant_conflicts(ours, "スーパーパラレル OP03-122") is False, ours


def test_no_marker_is_not_judged():
    assert H.candidate_variant_conflicts("【PSA10】ルフィ", "PSA10 ルフィ") is False
    assert H.candidate_variant_conflicts("", "") is False


def test_filter_splits_keep_and_drop():
    cands = [{"name": "ルフィ パラレル", "url": "u1"}, {"name": "ルフィ", "url": "u2"}]
    keep, drop = H.filter_candidates_by_variant(cands, "【PSA10】ルフィ ST13-015")
    assert [c["url"] for c in keep] == ["u2"]
    assert [c["url"] for c in drop] == ["u1"]


def test_reason_is_registered_everywhere():
    """理由の語彙が3か所 (STOP/WAIT/日本語) で揃っていること."""
    assert "all_variant" in H.STOP_REASONS
    assert "all_variant" in H.WAIT_REASONS
    assert "all_variant" in H._REASON_JA
