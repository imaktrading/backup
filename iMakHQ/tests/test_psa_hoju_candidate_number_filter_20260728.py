"""補URL 候補の番号足切り (2026-07-28).

確証UIに「明らかに別カード」が混ざり、人が毎回目で弾いていた。番号で機械的に落とす。
★除外しかしない: 一致しても自動採用はせず有人確証のまま。判定材料が無い候補は残す
  (落とすと供給の recall が減り、補URL 0本 = 死に直結するため)。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import psa_hoju_fill as P  # noqa: E402


def test_same_number_is_kept():
    assert P.candidate_number_conflicts("【PSA10】ブラッキーex RR sv8a 093/187", "SV8a-093") is False
    assert P.candidate_number_conflicts("PSA10 サボ OP13-004 パラレル", "OP13-004") is False


def test_different_number_is_dropped():
    assert P.candidate_number_conflicts("【PSA10】リザードンex SAR 201/165", "SV8a-093") is True
    assert P.candidate_number_conflicts("PSA10 ルフィ OP01-003", "OP13-004") is True


def test_zero_padding_difference_is_not_a_conflict():
    """'7/095' と 'SM10-007' は同じカード。ゼロ埋め差で落としてはいけない。"""
    assert P.candidate_number_conflicts("PSA10 レシラム＆リザードンGX 7/095", "SM10-007") is False


def test_unjudgeable_is_kept():
    """番号表記なし/候補名なし/対象番号なし = 判定しない (残して人に見せる)。"""
    assert P.candidate_number_conflicts("PSA10 なんかのカード", "SM10-007") is False
    assert P.candidate_number_conflicts("", "SM10-007") is False
    assert P.candidate_number_conflicts("【PSA10】何か 093/187", "") is False
    assert P.candidate_number_conflicts(None, "SM10-007") is False


def test_set_code_mismatch_with_same_number_is_dropped():
    """同じ番号でも set code が違えば別カード (OP13-004 と ST01-004)。"""
    assert P.candidate_number_conflicts("PSA10 なにか ST01-004", "OP13-004") is True


def test_filter_splits_keep_and_drop():
    cands = [{"name": "【PSA10】ブラッキーex sv8a 093/187", "url": "u1"},
             {"name": "【PSA10】リザードン 201/165", "url": "u2"},
             {"name": None, "url": "u3"}]
    keep, drop = P.filter_candidates_by_number(cands, "SV8a-093")
    assert [c["url"] for c in keep] == ["u1", "u3"]
    assert [c["url"] for c in drop] == ["u2"]


def test_filter_is_noop_when_target_number_unknown():
    cands = [{"name": "何か 001/100", "url": "u1"}]
    keep, drop = P.filter_candidates_by_number(cands, "")
    assert keep == cands and drop == []


def test_target_card_number_parsing():
    assert P._target_card_number("OP11-106") == ("OP11", 106)
    assert P._target_card_number("SV8a-093") == ("SV8A", 93)
    assert P._target_card_number("P-041") == ("P", 41)
    assert P._target_card_number("") == ("", None)
