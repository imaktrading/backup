# -*- coding: utf-8 -*-
"""夜の先貯めを自動出品と同じ順で取る / ランダム枠は鑑定データのある物から (2026-09-30 ユーザー確定)。

9/30 18:00 の走行: 枠を使ってから「既に出品中」で 19件落ち、19件とも走行時点で鑑定データが無かった。
前段の除外は鑑定データが無いと効かない。
"""
import os
import sys

_TCG = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "iMakTCG")
sys.path.insert(0, _TCG)

import psa_cache_warm as W  # noqa: E402
import tcg_batch_select as S  # noqa: E402


def _pop(known):
    f = lambda c: False            # noqa: E731
    f.known = lambda c: c in known
    return f


def test_explore_slot_prefers_known():
    certs = [str(i) for i in range(10)]
    titles = {c: "Pokemon" for c in certs}
    known = {"8", "9"}
    got = S.balanced_sample(certs, titles, 5, shuffle=lambda g: None, explore=0.4,
                            popular_of=_pop(known), card_of=lambda c: "", pokemon_share=0)
    assert got[:2] == ["8", "9"]          # ランダム枠 (5×0.4=2) は鑑定データのある物


def test_explore_falls_back_when_not_enough_known():
    certs = ["a", "b", "c"]
    got = S.balanced_sample(certs, {c: "Pokemon" for c in certs}, 3, shuffle=lambda g: None, explore=1.0,
                            popular_of=_pop(set()), card_of=lambda c: "", pokemon_share=0)
    assert sorted(got) == ["a", "b", "c"]


def test_warm_order_uses_listing_order_and_keeps_all():
    seen = {}

    def fake_sample(todo, title_map, limit, **kw):
        seen.update(kw)
        return list(reversed(todo))[:-1]           # 1件落ちても後ろに戻る

    got = W.order_like_listing(["1", "2", "3"], {}, {}, sample=fake_sample, popular=lambda t, m: None)
    assert got == ["3", "2", "1"]
    assert seen["explore"] == 0                     # 夜の側はランダムを入れない


def test_warm_order_falls_back_on_error():
    def boom(*a, **k):
        raise RuntimeError("x")
    assert W.order_like_listing(["1", "2"], {}, {}, sample=boom, popular=boom) == ["1", "2"]
