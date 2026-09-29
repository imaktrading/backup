# -*- coding: utf-8 -*-
"""前に人が「同じ」と確かめた仕入候補は、補URL③ で目視に出さず書く (2026-09-29 ユーザー確定)。

実例: バオッキーVSTAR S12a-214 の候補6本のうち5本は 9/27 に再仕入れ①で「同じ」と判定済みなのに、
補URL③ 補充でまた目視に出ていた (「一度『同じ』と確かめた物は確定でしょ。2回出される方が無駄」)。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import psa_hoju_fill as H  # noqa: E402
import psa_label_learned as PLL  # noqa: E402

U = "https://snkrdunk.com/apparels/103771/used/"


def test_known_same_is_split_off():
    uv = {U + "1": {"S12a-214": {"v": "same"}}, U + "2": {"S12a-214": {"v": "diff"}},
          U + "3": {"S11-001": {"v": "same"}}}
    cands = [{"url": U + "1"}, {"url": U + "2"}, {"url": U + "3"}, {"url": U + "4"}]
    same, rest = H.split_known_same(cands, "pokemon_tcg:S12a-214", PLL, uv)
    assert [c["url"] for c in same] == [U + "1"]                 # このカードで「同じ」の物だけ
    assert [c["url"] for c in rest] == [U + "2", U + "3", U + "4"]  # 別カードの「同じ」は効かせない


def test_without_records_everything_is_shown():
    cands = [{"url": U + "1"}]
    assert H.split_known_same(cands, "pokemon_tcg:S12a-214", None, None) == ([], cands)


def test_confirm_writes_known_same_and_counts_skip_them():
    import inspect
    src = inspect.getsource(H.run_daytime_confirm)
    assert "split_known_same(" in src and "auto_same" in src and "n_ui" in src
    assert "split_known_same(" in inspect.getsource(H.count_workload)
