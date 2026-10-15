# -*- coding: utf-8 -*-
"""2026-10-15 残務 №497: セット名の短縮が前置詞で始まる切れ端 (『of the New Era』等) を出さない。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_head_words_never_start_a_shortened_set():
    import tcg_listing_fields as T
    for w in ("of", "the", "in", "to", "a", "from", "with", "and", "&", "for"):
        assert w in T._SET_HEAD_SKIP


def test_long_title_shortens_set_without_preposition_head():
    """長いセット名を削る時、'from the Grand Line' のような前置詞の切れ端で始めない (直す前はこれが出た)"""
    import tcg_listing_fields as T
    f = {"C:Game": "One Piece TCG", "C:Set": "Memorial Collection from the Grand Line",
         "C:Card Number": "OP05-022", "C:Character": "Donquixote Rosinante", "C:Language": "Japanese"}
    t = T.build_title_from_fields(f)
    assert len(t) <= 80
    assert "Japanese from " not in t, t
    assert "Grand Line #OP05-022 Donquixote Rosinante" in t
