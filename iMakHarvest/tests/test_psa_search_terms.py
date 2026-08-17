"""tests/test_psa_search_terms - PSA10 収集キーワードの生成 (2026-08-17).

実測 (debug/probe_psa10_volume.py / probe_psa10_keywords.py):
  1 キーワード 15 件で頭打ち。 価格・送料条件を外しても増えない = 検索側の上限。
  一方 語を増やすとほぼ線形 (弾コード 10 語 → 148 件、 重複 2 件)。
→ 語数がそのまま収集件数になるので、 **語が減る変更が事故**。 それを固定する。
"""
from __future__ import annotations

import pytest

from scrapers import psa_search_terms as T

pytestmark = pytest.mark.offline


def test_default_covers_all_games():
    kws = T.build_keywords()
    assert len(kws) > 60  # 語数 ≒ 件数。 実測 15 件/語 なので 900 件規模
    for g in T.GAMES:
        assert any(c in k for k in kws for c in T.SET_CODES[g])


def test_all_keywords_prefixed_with_psa10():
    # 前置きが無いと PSA でないカードを大量に拾う
    assert all(k.startswith("PSA10 ") for k in T.build_keywords())


def test_no_duplicate_keywords():
    kws = T.build_keywords()
    assert len(kws) == len(set(kws))


def test_single_game_filter():
    kws = T.build_keywords(["onepiece"])
    assert "PSA10 OP01" in kws
    assert not any("SV1a" in k for k in kws)


def test_onepiece_covers_booster_extra_premium_start():
    kws = T.build_keywords(["onepiece"])
    for code in ("OP01", "OP14", "EB01", "PRB01", "ST01"):
        assert f"PSA10 {code}" in kws


def test_generic_terms_included_by_default():
    assert "PSA10 ワンピースカード" in T.build_keywords(["onepiece"])


def test_generic_can_be_excluded():
    kws = T.build_keywords(["onepiece"], include_generic=False)
    assert "PSA10 ワンピースカード" not in kws
    assert "PSA10 OP01" in kws


def test_unknown_game_is_ignored_not_crashing():
    assert T.build_keywords(["no_such_game"]) == []


def test_empty_list_falls_back_to_all_games():
    # [] は「指定なし」= 全部。 うっかり 0 語で走らせない
    assert T.build_keywords([]) == T.build_keywords()
