# -*- coding: utf-8 -*-
"""入れ替え(補4〜5本)は「今より ¥1,000以上 安い」候補だけ目視に出す (2026-09-09 ユーザー確定)。

  「補は十分にあるからねー。1000円以上にしようか」

同額の候補は入れ替わらないのに目視だけさせる = 押しても何も変わらないカードが出る。
実測 2026-09-09: 入れ替えに出ていた55件のうち10件は同額の候補しか無かった。
★補充 (補0〜3本) には効かせない。丸腰の札にとって同額の仕入元は値下げではなく **予備の本数**。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "tools"))
import psa_hoju_fill as H          # noqa: E402


def test_同額は入れ替えに出さない():
    assert H.candidate_cost_conflicts(5000, 5000, False, H.SWAP_MIN_GAIN) is True


def test_千円未満しか安くない候補も出さない():
    assert H.candidate_cost_conflicts(4001, 5000, False, H.SWAP_MIN_GAIN) is True


def test_ちょうど千円安いなら出す():
    assert H.candidate_cost_conflicts(4000, 5000, False, H.SWAP_MIN_GAIN) is False


def test_補充側は同額でも出す():
    """予備の本数そのものなので、値下げでなくても価値がある。"""
    assert H.candidate_cost_conflicts(5000, 5000, False, 0) is False


def test_主が売り切れなら閾値を問わず出す():
    """供給ゼロの札は高くても押さえる価値がある (既存の fail-open を壊さない)。"""
    assert H.candidate_cost_conflicts(99999, 5000, True, H.SWAP_MIN_GAIN) is False


def test_値段が分からない候補は落とさない():
    assert H.candidate_cost_conflicts(None, 5000, False, H.SWAP_MIN_GAIN) is False
    assert H.candidate_cost_conflicts(5000, None, False, H.SWAP_MIN_GAIN) is False


def test_閾値は補URLの本数で決まる_ボタンの引数ではない():
    """パネルの件数(count_workload)と実走行が同じ関数を通るので、ここ1か所で決める。"""
    assert H.min_gain_for({"n_backups": 5}) == H.SWAP_MIN_GAIN
    assert H.min_gain_for({"n_backups": 4}) == H.SWAP_MIN_GAIN   # 入れ替えの下限
    assert H.min_gain_for({"n_backups": 3}) == 0                 # ここから補充
    assert H.min_gain_for({"n_backups": 0}) == 0
    assert H.min_gain_for({}) == 0


def test_フィルタが行の本数を見て効く():
    """filter_candidates_by_cost は t の n_backups だけで閾値を切り替える。"""
    vals = [["h"] * 20, [""] * 20]
    vals[1][13] = "5000"                       # N列 = 今の仕入値
    cands = [{"url": "https://jp.mercari.com/item/mSAME", "price": 5000},
             {"url": "https://jp.mercari.com/item/mCHEAP", "price": 3500}]
    H._PRICE_CACHE["v"] = {H._norm_url(c["url"]): c["price"] for c in cands}
    try:
        swap = {"row": 2, "n_backups": 5}
        keep, drop = H.filter_candidates_by_cost(cands, swap, vals)
        assert [c["url"] for c in keep] == ["https://jp.mercari.com/item/mCHEAP"]
        assert len(drop) == 1
        refill = {"row": 2, "n_backups": 1}
        keep2, drop2 = H.filter_candidates_by_cost(cands, refill, vals)
        assert len(keep2) == 2 and not drop2
    finally:
        H._PRICE_CACHE.pop("v", None)
