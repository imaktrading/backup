# -*- coding: utf-8 -*-
"""重複語除去が名前を壊して出品された (2026-08-24 実害)。

## 何が起きたか
```
前: PSA 10 One Piece Japanese PURPLE Monkey D. Luffy #OP05-060 Monkey D. Luffy
後: PSA 10 One Piece Japanese PURPLE Monkey D. Luffy #OP05-060 D.
```
2つ目の `Monkey` と `Luffy` が重複語として消え、`D.` は英字語でない (ピリオド付き) ので
除去対象にならず取り残された。この壊れた末尾のまま **eBay に出た**
(ItemID 820038886892 / 07:5x に修正済)。

裏の自動対応は 06:58 に CSV を直したが、入稿はその前に走っていて間に合わなかった。

## 直し方の勘所
「末尾のイニシャルを落とす」だけでは足りない。`Flying Pikachu V` の `V` は
**カード名の一部**で、落とすと別のカードになる。
**続く語が重複除去で消えた時だけ**イニシャルも一緒に落とす。
"""
import os
import sys

import pytest

_TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "iMakTCG", "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

from post_title_fix import remove_duplicate_words as R  # noqa: E402


def test_the_actual_broken_title():
    """★実害そのもの。`D.` が取り残されないこと。"""
    got, changed = R("PSA 10 One Piece Japanese PURPLE Monkey D. Luffy "
                     "#OP05-060 Monkey D. Luffy")
    assert changed
    assert not got.rstrip().endswith("D."), got
    assert got == "PSA 10 One Piece Japanese PURPLE Monkey D. Luffy #OP05-060"


@pytest.mark.parametrize("title", [
    # ★V はカード名の一部。落としたら別のカードになる
    "PSA 10 Pokemon Japanese 25th Anniversary Collection #023/028 Flying Pikachu V",
    "PSA 10 Pokemon Japanese Something #001/100 Charizard V",
    # 重複が無い普通のタイトル
    "PSA 10 One Piece Japanese Something #OP01-001 Monkey D. Luffy",
    "PSA 10 Pokemon Japanese Sv1s: Scarlet Ex #093/078 Great Tusk ex Super Rare",
])
def test_untouched_titles(title):
    got, changed = R(title)
    assert (got, changed) == (title, False)


def test_v_that_repeats_is_kept_by_whitelist():
    """`V` が2回出ても、カード用語なので消さない (既存の whitelist の役目)。"""
    got, changed = R("PSA 10 Pokemon V Something #001 Pikachu V")
    assert got.endswith("Pikachu V") and not changed


def test_chain_of_initials():
    got, _ = R("A B. C. Name #001 A B. C. Name")
    assert got == "A B. C. Name #001"


def test_normal_dedup_still_works():
    """本来の仕事 (重複語を消す) は変わっていないこと。"""
    got, changed = R("PSA 10 One Piece Japanese Booster One Piece The Best "
                     "#DON-PRB01-020 DON!! Card")
    assert changed and got == ("PSA 10 One Piece Japanese Booster The Best "
                               "#DON-PRB01-020 DON!! Card")


def test_no_change_on_past_output():
    """過去に出したタイトル 614件に当てて、1件も変わらないこと (回帰なし)。"""
    import csv
    import glob
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    n = changed = 0
    for f in glob.glob(os.path.join(root, "iMakHQ", "csv_output", "tcg_upload_*.csv")):
        try:
            rows = list(csv.reader(open(f, newline="", encoding="utf-8")))
        except Exception:
            continue
        if len(rows) < 2 or "*Title" not in rows[0]:
            continue
        ti = rows[0].index("*Title")
        for r in rows[1:]:
            t = (r[ti] if ti < len(r) else "").strip()
            if not t:
                continue
            n += 1
            if R(t)[1]:
                changed += 1
    if n:                       # csv_output が空の環境では素通り
        assert changed == 0, f"{n}件中 {changed}件が変わった"


# ── カード名そのものを壊さない (2026-08-24 夜 実害) ────────────────
# `Tony Tony Chopper` は Tony が2回入るのが正式名。重複語除去が2つ目の Tony を消し、
# `Tony Chopper` = **別の名前**のまま出品された (ItemID 820041238874 / 修正済)。
# カタログの名前は写すだけの値なので、後処理で削ってはいけない。


def test_doubled_word_in_the_card_name_survives():
    got, _ = R("PSA 10 One Piece Japanese One Piece Chopper's 1 "
               "#EB02-003 Tony Tony Chopper Rare", card_name="Tony Tony Chopper")
    assert "Tony Tony Chopper" in got, got


def test_set_name_dedup_still_happens_around_the_protected_name():
    """名前を守っても、セット名でない並びの重複は今までどおり消えること。

    ★2026-08-28 に題材を差し替えた。元は `One Piece Chopper's 1` を使い、そこから
      `One Piece` が消えることを期待していたが、これは **確定済のセット名**
      (promo_overrides.json) で、消すと別のセット名になる = 直した側の不具合。
      題材だけ「カタログにもプロモにも無い並び」に替え、assert は緩めていない。
    """
    got, changed = R("PSA 10 One Piece Japanese Booster One Piece The Best "
                     "#EB02-003 Tony Tony Chopper Rare", card_name="Tony Tony Chopper")
    assert changed and got.count("One Piece") == 1
    assert "Tony Tony Chopper" in got, got


def test_card_name_inside_the_set_name_is_not_stripped():
    """セット名にカード名が入る形 (`Great Detective Pikachu` + `Detective Pikachu`)。

    どちらかを消すと、セット名かカード名のどちらかが壊れる。両方残す。
    """
    got, changed = R("PSA 10 Pokemon Japanese Smp2: Great Detective Pikachu "
                     "#014/024 Detective Pikachu", card_name="Detective Pikachu")
    assert not changed and got.endswith("#014/024 Detective Pikachu")


def test_protects_the_last_occurrence():
    """守るのは **カード名の側** (後ろ)。前に出る同じ語はセット名の一部。"""
    import post_title_fix as M
    parts = "A Great Detective Pikachu X Detective Pikachu".split()
    assert M._protected_span(parts, "Detective Pikachu") == {5, 6}


def test_no_card_name_behaves_as_before():
    """名前が渡らない時は従来どおり (呼び出し側が古くても壊れない)。"""
    got, changed = R("PSA 10 One Piece Japanese Booster One Piece The Best "
                     "#DON-PRB01-020 DON!! Card")
    assert changed and got.count("One Piece") == 1


def test_card_name_not_present_in_title_is_a_noop():
    got, changed = R("PSA 10 Pokemon Japanese Set #001 Pikachu",
                     card_name="Charizard ex")
    assert not changed
