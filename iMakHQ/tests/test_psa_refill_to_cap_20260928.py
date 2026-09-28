# -*- coding: utf-8 -*-
"""仕入元を読んだ後に減った分を補う (2026-09-28)。

ユーザー「20件を候補として、10件というのが少ない」「CAP 20件は 20件出品したいから」
「時間ばかり長くなっても困る」。18:30 の自動は 20件選んで 5件が出品中と同じカードで抜けた。
"""
import os
import re

TCG = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "iMakTCG")


def _src():
    return open(os.path.join(TCG, "psa_to_csv.py"), encoding="utf-8").read()


def test_refill_loop_is_bounded_and_before_review():
    s = _src()
    m = re.search(r"_REFILL_ROUNDS = (\d+)", s)
    assert m and 1 <= int(m.group(1)) <= 3          # 周回に上限 (走る時間を延ばしすぎない)
    i_loop = s.index("_REFILL_ROUNDS = ")
    i_review = s.index("from post_psa_review import run_pre_build_verify")
    assert i_loop < i_review                         # 目視より前で補う (目視は1回のまま)


def test_refill_picks_from_untried_pool_with_same_ranking():
    s = _src()
    assert "_pool_all = list(cert_numbers)" in s
    assert "_rest = [_c for _c in _pool_all if _c not in _tried]" in s
    assert "_bs(_rest, mercari_title_map, _need" in s   # 最初の20件と同じ並べ方で選ぶ
