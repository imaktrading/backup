# -*- coding: utf-8 -*-
"""重複語除去が **セット名の中の `One Piece`** を食っていた (2026-08-28)。

```
旧: PSA 10 One Piece Japanese One Piece Day #ST10-006 Monkey D. Luffy Super Rare
新: PSA 10 One Piece Japanese Day #ST10-006 …                    ← 「One Piece Day」が壊れる
旧: PSA 10 One Piece Japanese Premium Booster One Piece The Best #OP01-006 Otama
新: PSA 10 One Piece Japanese Premium Booster The Best #OP01-006 …  ← 同上
```
どちらも 2026-08-26 の走行で出た実物。`Tony Tony Chopper` (a72586f) /
末尾 `D.` (1919b22) と同じ形の3回目なので、カード個別ではなく **何がセット名かを
知らないこと** を直した (catalog の set_name_ebay + 確定済 promo 名を見る)。

この4本は 依頼書 2026-08-28_word_dedup_eats_one_piece_in_set_name.md の必須回帰。
"""
import os
import sys

import pytest

_TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "iMakTCG", "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

from post_title_fix import remove_duplicate_words as R  # noqa: E402


@pytest.mark.parametrize("title", [
    # ① セット名 = 確定済 promo 名 `One Piece Day`
    "PSA 10 One Piece Japanese One Piece Day #ST10-006 Monkey D. Luffy Super Rare",
    # ② セット名 = catalog の set_name_ebay `Premium Booster One Piece The Best`
    "PSA 10 One Piece Japanese Premium Booster One Piece The Best #OP01-006 Otama",
])
def test_set_name_containing_the_game_name_survives(title):
    assert R(title) == (title, False)


def test_card_name_with_a_doubled_word_survives():
    """③ `Tony Tony Chopper` は Tony が2回入るのが正式名 (2026-08-24 実害)。"""
    got, _ = R("PSA 10 One Piece Japanese One Piece Chopper's 1 "
               "#EB02-003 Tony Tony Chopper Rare", card_name="Tony Tony Chopper")
    assert "Tony Tony Chopper" in got, got


def test_no_orphan_initial_left_behind():
    """④ 末尾に `D.` だけ取り残さない (2026-08-24 実害)。"""
    got, changed = R("PSA 10 One Piece Japanese PURPLE Monkey D. Luffy "
                     "#OP05-060 Monkey D. Luffy")
    assert changed
    assert got == "PSA 10 One Piece Japanese PURPLE Monkey D. Luffy #OP05-060", got


# ── 発生源を直したことの確認 (個別カードの当て込みでないこと) ──────────
def test_the_protected_phrases_come_from_catalog_and_promo_store():
    """守る語列は catalog の set_name_ebay と確定済 promo 名だけ (ここで語を足さない)。"""
    import post_title_fix as M
    idx = M.known_set_phrase_index()
    assert idx, "セット名の索引が空 = 守りが効いていない"
    assert ("one", "piece", "day") in idx["one"]                     # promo_overrides.json
    assert ("premium", "booster", "one", "piece", "the", "best") in idx["premium"]  # catalog
    assert all(len(t) >= 2 for v in idx.values() for t in v), "1語の並びは入れない"


def test_only_the_first_set_phrase_is_protected():
    """セット名と同じ名前のカードで **末尾まで守らない** (④ が無効になるため)。

    `PURPLE Monkey D. Luffy` は catalog の set_name_ebay にも在る。全出現を守ると
    2026-08-24 の壊れた末尾がそのまま残る。
    """
    import post_title_fix as M
    parts = ("PSA 10 One Piece Japanese PURPLE Monkey D. Luffy "
             "#OP05-060 Monkey D. Luffy").split()
    assert M._set_phrase_spans(parts) == {5, 6, 7, 8}
