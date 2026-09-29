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


def test_snkrdunk_same_product_page_counts_as_same():
    # 729387 のページの出品を1本「同じ」と確かめていれば、同じページの新しい出品も同じカード
    uv = {U.replace("103771", "729387") + "10": {"M2a-199": {"v": "same"}}}
    cands = [{"url": "https://snkrdunk.com/apparels/729387/used/99"},
             {"url": "https://snkrdunk.com/apparels/111111/used/5"},
             {"url": "https://jp.mercari.com/item/m1"}]
    same, rest = H.split_known_same(cands, "pokemon_tcg:M2a-199", PLL, uv)
    assert [c["url"] for c in same] == ["https://snkrdunk.com/apparels/729387/used/99"]
    assert len(rest) == 2                                          # 別ページ・メルカリは目視へ


def test_snkrdunk_page_with_any_diff_is_not_trusted():
    base = "https://snkrdunk.com/apparels/729387/used/"
    uv = {base + "1": {"M2a-199": {"v": "same"}}, base + "2": {"M2a-199": {"v": "diff"}}}
    same, rest = H.split_known_same([{"url": base + "3"}], "pokemon_tcg:M2a-199", PLL, uv)
    assert same == [] and len(rest) == 1


def test_restock_screen_marks_known_same():
    """再仕入れ①は買う先を選ぶ画面なので自動にはしない。前に「同じ」の候補に印を出す。"""
    import inspect
    import psa_resource_confirm as C
    import psa_resource_gate as G
    assert "known_same" in inspect.getsource(G._build_visual_candidates)
    assert "前に同じと確認済み" in inspect.getsource(C)
